"""Извлечение одной белковой последовательности из файлов SnapGene и GenBank."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from Bio import SeqIO
from Bio.Seq import Seq

import autosnapgene


MIN_PROTEIN_LENGTH = 80
SUPPORTED_SUFFIXES = frozenset({".dna", ".gb", ".genbank"})


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Результат разбора одного входного файла без побочных действий."""

    source_path: Path
    filename: str
    sequence: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        """Признак того, что белковая последовательность извлечена."""

        return self.sequence is not None and self.error is None


def parse_sequence_file(path: str | Path) -> ParseResult:
    """Разбирает файл и возвращает самую длинную пригодную белковую цепь.

    Ошибки входного файла преобразуются в русскоязычную диагностику: исключения
    намеренно не передаются вызывающему коду, чтобы один файл не прерывал job.
    """

    source_path = Path(path)
    filename = source_path.name
    suffix = source_path.suffix.lower()

    if suffix not in SUPPORTED_SUFFIXES:
        return _failure(source_path, "Неподдерживаемое расширение файла: " + (suffix or "без расширения"))
    if not source_path.is_file():
        return _failure(source_path, "Входной файл не найден или недоступен")

    try:
        if suffix == ".dna":
            candidates = _parse_snapgene(source_path)
        else:
            candidates = _parse_genbank(source_path)
        sequence = _longest_protein(candidates)
    except Exception as error:
        return _failure(source_path, f"Не удалось разобрать файл: {_error_details(error)}")

    if sequence is None:
        return _failure(
            source_path,
            f"В файле {filename} не найдена белковая последовательность длиной не менее {MIN_PROTEIN_LENGTH} а.к.",
        )
    return ParseResult(source_path=source_path, filename=filename, sequence=sequence)


def _failure(source_path: Path, reason: str) -> ParseResult:
    """Создаёт неуспешный результат с безопасной диагностикой."""

    return ParseResult(source_path=source_path, filename=source_path.name, error=reason)


def _parse_genbank(path: Path) -> Iterable[str]:
    """Извлекает кандидаты из features всех записей GenBank."""

    for record in SeqIO.parse(path, "genbank"):
        for feature in record.features:
            translation = _translation_from_qualifier(feature)
            if translation is not None:
                yield translation
                continue
            protein = _translate_genbank_feature(feature, record.seq)
            if protein is not None:
                yield protein


def _parse_snapgene(path: Path) -> Iterable[str]:
    """Извлекает кандидаты из всех features SnapGene."""

    snapgene_file = autosnapgene.SnapGene(str(path))
    for feature in snapgene_file.features:
        translation = _translation_from_qualifier(feature)
        if translation is not None:
            yield translation
            continue
        protein = _translate_snapgene_feature(feature, snapgene_file.sequence)
        if protein is not None:
            yield protein


def _translation_from_qualifier(feature: Any) -> str | None:
    """Возвращает очищенный qualifier ``translation``, если он задан."""

    qualifiers = getattr(feature, "qualifiers", {})
    translation = qualifiers.get("translation")
    if isinstance(translation, (list, tuple)):
        translation = translation[0] if translation else None
    if not isinstance(translation, str):
        return None
    return _clean_protein(translation)


def _translate_genbank_feature(feature: Any, record_sequence: Seq) -> str | None:
    """Транслирует feature GenBank, доверяя Biopython orientation и compound location."""

    location = getattr(feature, "location", None)
    if location is None:
        return None
    try:
        nucleotides = feature.extract(record_sequence)
    except Exception:
        return None
    return _translate_nucleotides(nucleotides, _codon_start(feature))


def _translate_snapgene_feature(feature: Any, full_sequence: str) -> str | None:
    """Транслирует feature SnapGene с учётом сегментов, направления и codon_start."""

    try:
        nucleotides = "".join(
            str(full_sequence[start:end]) for start, end in (segment.range for segment in feature.segments)
        )
    except Exception:
        return None
    if getattr(feature, "directionality", None) == "backward":
        nucleotides = str(Seq(nucleotides).reverse_complement())
    return _translate_nucleotides(nucleotides, _codon_start(feature))


def _codon_start(feature: Any) -> int:
    """Возвращает корректный однобазовый сдвиг кадра чтения."""

    value = getattr(feature, "qualifiers", {}).get("codon_start", 1)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else 1
    try:
        codon_start = int(value)
    except (TypeError, ValueError):
        return 1
    return codon_start if codon_start in {1, 2, 3} else 1


def _translate_nucleotides(nucleotides: str | Seq, codon_start: int) -> str | None:
    """Транслирует нуклеотиды до первого стоп-кодона без предупреждений о хвосте."""

    offset = codon_start - 1
    sequence = str(nucleotides)[offset:]
    usable_length = len(sequence) - len(sequence) % 3
    if usable_length == 0:
        return None
    try:
        protein = Seq(sequence[:usable_length]).translate(to_stop=True)
    except Exception:
        return None
    return _clean_protein(str(protein))


def _clean_protein(sequence: str) -> str | None:
    """Удаляет пробелы и терминальный хвост после стоп-кодона из белка."""

    cleaned = "".join(sequence.split()).upper()
    if "*" in cleaned:
        cleaned = cleaned.split("*", maxsplit=1)[0]
    if not cleaned or not cleaned.isascii() or not cleaned.isalpha():
        return None
    return cleaned


def _longest_protein(candidates: Iterable[str | None]) -> str | None:
    """Выбирает ровно одну наиболее длинную последовательность допустимого размера."""

    best: str | None = None
    for candidate in candidates:
        if candidate is None or len(candidate) < MIN_PROTEIN_LENGTH:
            continue
        if best is None or len(candidate) > len(best):
            best = candidate
    return best


def _error_details(error: Exception) -> str:
    """Ограничивает технический текст ошибки, сохраняя полезную причину."""

    details = " ".join(str(error).split())
    return details[:300] if details else "неизвестная ошибка формата"
