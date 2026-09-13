"""Извлечение одной белковой последовательности из файлов SnapGene и GenBank."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import re
from typing import Any, Iterable

from Bio import SeqIO
from Bio.Seq import Seq

import autosnapgene


MIN_PROTEIN_LENGTH = 80
SUPPORTED_SUFFIXES = frozenset({".dna", ".gb", ".genbank"})
NUCLEOTIDE_ALPHABET = frozenset("ACGTRYSWKMBDHVN")


@dataclass(frozen=True, slots=True)
class ParsedCandidate:
    """Белок и нуклеотиды одной исходной feature."""

    protein: str
    nucleotide: str | None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Результат разбора одного входного файла без записи артефактов."""

    source_path: Path
    filename: str
    sequence: str | None = None
    nucleotide_sequence: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        """Признак того, что белковая последовательность извлечена."""

        return self.sequence is not None and self.error is None


def parse_sequence_file(path: str | Path) -> ParseResult:
    """Разбирает файл и возвращает белок с нуклеотидами выбранной feature.

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
        candidate = _longest_protein(candidates)
    except Exception as error:
        return _failure(source_path, f"Не удалось разобрать файл: {_error_details(error)}")

    if candidate is None:
        return _failure(
            source_path,
            f"В файле {filename} не найдена белковая последовательность длиной не менее {MIN_PROTEIN_LENGTH} а.к.",
        )
    return ParseResult(
        source_path=source_path,
        filename=filename,
        sequence=candidate.protein,
        nucleotide_sequence=candidate.nucleotide,
    )


def _failure(source_path: Path, reason: str) -> ParseResult:
    """Создаёт неуспешный результат с безопасной диагностикой."""

    return ParseResult(source_path=source_path, filename=source_path.name, error=reason)


def _parse_genbank(path: Path) -> Iterable[ParsedCandidate]:
    """Извлекает кандидаты из features всех записей GenBank."""

    try:
        records = list(SeqIO.parse(path, "genbank"))
    except (UnicodeDecodeError, ValueError) as error:
        if isinstance(error, ValueError) and "Did not recognise the LOCUS line layout" not in str(error):
            raise
        records = list(_parse_genbank_with_normalized_locus(path))

    for record in records:
        for feature in record.features:
            translation = _translation_from_qualifier(feature)
            nucleotide = _extract_genbank_nucleotides(feature, record.seq)
            protein = translation or _translate_nucleotides_for_candidate(nucleotide, feature)
            if protein is not None:
                yield ParsedCandidate(protein, nucleotide)


def _parse_genbank_with_normalized_locus(path: Path) -> Iterable[Any]:
    """Повторно разбирает GenBank после нормализации имени в строке ``LOCUS``.

    В ряде файлов SnapGene имя записи состоит из нескольких слов, например
    ``LOCUS Untitled 3 483 bp DNA linear UNA 25-AUG-2022``. Biopython не
    принимает такую строку, так как пробел внутри имени сдвигает остальные
    поля. Имя записи далее не используется, поэтому для чтения оно безопасно
    заменяется односоставным вариантом.
    """

    content = _read_genbank_text(path)
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.startswith("LOCUS"):
            continue
        normalized = _normalize_locus_line(line)
        if normalized is not None:
            lines[index] = normalized
            break
    return SeqIO.parse(StringIO("".join(lines)), "genbank")


def _read_genbank_text(path: Path) -> str:
    """Читает текст GenBank без предположения, что служебные поля сохранены в UTF-8.

    Нуклеотидная часть GenBank ASCII-совместима, а не-UTF-8 байты обычно находятся
    в аннотациях, созданных SnapGene. Сначала сохраняем стандартную UTF-8
    интерпретацию, затем используем Windows-1251 для русскоязычных аннотаций и
    Latin-1 как безошибочный последний вариант.
    """

    data = path.read_bytes()
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _normalize_locus_line(line: str) -> str | None:
    """Нормализует однострочный вариант ``LOCUS`` для fallback-разбора."""

    match = re.match(
        r"^LOCUS\s+(.+?)\s+(\d+)\s+(bp|aa)\s+(.+?)(\r?\n)?$",
        line,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None

    name, length, unit, remainder, line_ending = match.groups()
    normalized_name = re.sub(r"\s+", "_", name.strip())
    return f"LOCUS       {normalized_name} {length} {unit} {remainder.strip()}{line_ending or ''}"


def _parse_snapgene(path: Path) -> Iterable[ParsedCandidate]:
    """Извлекает кандидаты из всех features SnapGene."""

    snapgene_file = autosnapgene.SnapGene(str(path))
    for feature in snapgene_file.features:
        translation = _translation_from_qualifier(feature)
        nucleotide = _extract_snapgene_nucleotides(feature, snapgene_file.sequence)
        protein = translation or _translate_nucleotides_for_candidate(nucleotide, feature)
        if protein is not None:
            yield ParsedCandidate(protein, nucleotide)


def _translation_from_qualifier(feature: Any) -> str | None:
    """Возвращает очищенный qualifier ``translation``, если он задан."""

    qualifiers = getattr(feature, "qualifiers", {})
    translation = qualifiers.get("translation")
    if isinstance(translation, (list, tuple)):
        translation = translation[0] if translation else None
    if not isinstance(translation, str):
        return None
    return _clean_protein(translation)


def _extract_genbank_nucleotides(feature: Any, record_sequence: Seq) -> str | None:
    """Извлекает ровно нуклеотиды feature с учётом compound location."""

    location = getattr(feature, "location", None)
    if location is None:
        return None
    try:
        nucleotides = feature.extract(record_sequence)
    except Exception:
        return None
    return _clean_nucleotide(str(nucleotides))


def _extract_snapgene_nucleotides(feature: Any, full_sequence: str) -> str | None:
    """Извлекает ровно сегменты SnapGene feature в кодирующем направлении."""

    try:
        nucleotides = "".join(
            str(full_sequence[start:end]) for start, end in (segment.range for segment in feature.segments)
        )
    except Exception:
        return None
    if getattr(feature, "directionality", None) == "backward":
        nucleotides = str(Seq(nucleotides).reverse_complement())
    return _clean_nucleotide(nucleotides)


def _translate_nucleotides_for_candidate(nucleotides: str | None, feature: Any) -> str | None:
    """Транслирует извлечённую feature только при отсутствии готового translation."""

    if nucleotides is None:
        return None
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


def _longest_protein(candidates: Iterable[ParsedCandidate]) -> ParsedCandidate | None:
    """Выбирает ровно одну наиболее длинную последовательность допустимого размера."""

    best: ParsedCandidate | None = None
    for candidate in candidates:
        if len(candidate.protein) < MIN_PROTEIN_LENGTH:
            continue
        if best is None or len(candidate.protein) > len(best.protein):
            best = candidate
    return best


def _clean_nucleotide(sequence: str) -> str | None:
    """Нормализует только последовательность, извлечённую из feature."""

    cleaned = "".join(sequence.split()).upper()
    if not cleaned or not set(cleaned).issubset(NUCLEOTIDE_ALPHABET):
        return None
    return cleaned


def _error_details(error: Exception) -> str:
    """Ограничивает технический текст ошибки, сохраняя полезную причину."""

    details = " ".join(str(error).split())
    return details[:300] if details else "неизвестная ошибка формата"
