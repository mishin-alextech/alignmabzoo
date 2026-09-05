"""Преобразование нумерации ANARCI и координат CDR в позиции MSA."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence


SchemeName = Literal["imgt", "kabat", "chothia"]
CHAIN_SCHEMES: tuple[SchemeName, ...] = ("imgt", "kabat", "chothia")
_GAP_CHARACTERS = frozenset({"-", "."})
_POSITION_PATTERN = re.compile(r"^(?:[HKL])?\s*(\d+)\s*([A-Za-z]*)$")


@dataclass(frozen=True, slots=True)
class ResidueNumber:
    """Номер аминокислоты в схеме ANARCI, включая буквенную вставку."""

    position: int
    insertion: str = ""
    residue: str | None = None

    @property
    def label(self) -> str:
        """Возвращает отображаемую метку, например ``35A``."""

        return f"{self.position}{self.insertion}"


@dataclass(frozen=True, slots=True)
class ParsedNumbering:
    """Нумерация одной доменной цепи, извлечённая из CSV ANARCI."""

    residues: tuple[ResidueNumber, ...]
    chain_type: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class CdrIndices:
    """Индексы трёх CDR в строке множественного выравнивания."""

    cdr1: tuple[int, ...]
    cdr2: tuple[int, ...]
    cdr3: tuple[int, ...]

    def as_dict(self) -> dict[str, list[int]]:
        """Возвращает JSON-совместимое представление для viewer."""

        return {
            "cdr1": list(self.cdr1),
            "cdr2": list(self.cdr2),
            "cdr3": list(self.cdr3),
        }


_CDR_BOUNDARIES: dict[SchemeName, dict[str, tuple[tuple[int, int], ...]]] = {
    # Границы включительны. Вставки относятся к той же числовой позиции.
    "imgt": {"universal": ((27, 38), (56, 65), (105, 117))},
    "kabat": {
        "heavy": ((31, 35), (50, 65), (95, 102)),
        "light": ((24, 34), (50, 56), (89, 97)),
    },
    "chothia": {
        "heavy": ((26, 32), (52, 56), (95, 102)),
        "light": ((24, 34), (50, 56), (89, 97)),
    },
}


def parse_anarci_csv(path: str | Path) -> ParsedNumbering:
    """Читает стандартный CSV ANARCI без предположений о CDR-полях.

    Выпуски ANARCI встречаются с длинной формой CSV (колонки номера,
    вставки и остатка) и с широкой формой, где номера находятся в
    заголовках. Поддерживаются обе формы; если нумерации нет, вызывающий
    код получает диагностическое предупреждение, а не ложную аннотацию.
    """

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as error:
        return ParsedNumbering((), warning=f"Не удалось прочитать CSV ANARCI: {error}")
    return parse_anarci_csv_text(text)


def parse_anarci_csv_records(path: str | Path) -> dict[str, ParsedNumbering]:
    """Читает общий CSV ANARCI и возвращает нумерацию отдельно по колонке ``Id``."""

    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = tuple(reader.fieldnames or ())
        rows = tuple(reader)
    except (OSError, csv.Error):
        return {}
    id_column = _find_column(headers, "id", "name", "sequence_id")
    if id_column is None:
        parsed = parse_anarci_csv_text(text)
        return {"": parsed}

    rows_by_identifier: dict[str, list[dict[str | None, str | None]]] = {}
    for row in rows:
        identifier = (row.get(id_column) or "").strip()
        if not identifier:
            continue
        rows_by_identifier.setdefault(identifier, []).append(row)

    # Не отбрасываем строку с известным Id, даже если её позиции не удалось
    # разобрать. Вызывающий код тогда отличит проблему формата от отсутствия
    # последовательности в CSV ANARCI.
    return {
        identifier: _parse_anarci_rows(headers, identifier_rows)
        for identifier, identifier_rows in rows_by_identifier.items()
    }


def parse_anarci_csv_text(text: str) -> ParsedNumbering:
    """Разбирает содержимое CSV ANARCI в порядке остатков домена."""

    try:
        reader = csv.DictReader(io.StringIO(text))
        headers = tuple(reader.fieldnames or ())
        rows = tuple(reader)
    except csv.Error as error:
        return ParsedNumbering((), warning=f"Некорректный CSV ANARCI: {error}")

    if not headers:
        return ParsedNumbering((), warning="CSV ANARCI не содержит заголовка")
    if not rows:
        return ParsedNumbering((), warning="CSV ANARCI не содержит строк нумерации")

    return _parse_anarci_rows(headers, rows)


def _parse_anarci_rows(
    headers: Sequence[str], rows: Sequence[dict[str | None, str | None]]
) -> ParsedNumbering:
    """Разбирает строки одной последовательности из общего CSV ANARCI."""

    chain_column = _find_column(headers, "chain_type", "chain", "chain type")
    chain_type = _first_nonempty(rows, chain_column) if chain_column else None
    position_column = _find_column(
        headers,
        "position",
        "number",
        "numbering",
        "scheme_position",
        "imgt_position",
        "kabat_position",
        "chothia_position",
    )
    residue_column = _find_column(
        headers,
        "residue",
        "aa",
        "amino_acid",
        "amino acid",
        "aminoacid",
    )
    insertion_column = _find_column(headers, "insertion", "insert", "insertion_code")

    if position_column and residue_column:
        residues = _parse_long_rows(rows, position_column, residue_column, insertion_column)
        if residues:
            return ParsedNumbering(tuple(residues), chain_type=chain_type)

    residues = _parse_wide_rows(headers, rows)
    if residues:
        return ParsedNumbering(tuple(residues), chain_type=chain_type)

    has_numbered_headers = any(parse_numbering_label(header) is not None for header in headers)
    if position_column and residue_column:
        warning = "В строке последовательности CSV ANARCI есть колонки нумерации, но нет распознаваемых аминокислот."
    elif has_numbered_headers:
        warning = "В строке последовательности CSV ANARCI есть заголовки позиций, но нет распознаваемых аминокислот."
    else:
        warning = "В строке последовательности CSV ANARCI не найдены позиции нумерации аминокислот."
    return ParsedNumbering(
        (),
        chain_type=chain_type,
        warning=warning,
    )


def build_alignment_numbering(
    aligned_sequence: str,
    residues: Sequence[ResidueNumber],
) -> list[str | None]:
    """Переносит номера в координаты MSA; все gap получают ``None``.

    Остатки CSV сопоставляются в их естественном порядке. Если нумерация
    неполная, неразмеченные аминокислоты также остаются ``None`` — это
    безопаснее, чем приписывать им выдуманные номера.
    """

    numbering: list[str | None] = [None] * len(aligned_sequence)
    usable_residues = [item for item in residues if item.residue not in _GAP_CHARACTERS]
    residue_index = 0
    for alignment_index, character in enumerate(aligned_sequence):
        if character in _GAP_CHARACTERS:
            continue
        if residue_index >= len(usable_residues):
            continue
        numbering[alignment_index] = usable_residues[residue_index].label
        residue_index += 1
    return numbering


def cdr_indices_for_alignment(
    aligned_sequence: str,
    residues: Sequence[ResidueNumber],
    scheme: SchemeName,
    chain_group: str | None = None,
    chain_type: str | None = None,
) -> CdrIndices:
    """Возвращает CDR как индексы выровненной строки, а не номера схемы."""

    family = chain_family(chain_type) or chain_family(chain_group)
    boundaries = _boundaries_for_scheme(scheme, family)
    if boundaries is None:
        return CdrIndices((), (), ())

    numbering = build_alignment_numbering(aligned_sequence, residues)
    indexes: list[list[int]] = [[], [], []]
    for alignment_index, label in enumerate(numbering):
        if label is None:
            continue
        position = parse_numbering_label(label)
        if position is None:
            continue
        for cdr_index, (start, end) in enumerate(boundaries):
            if start <= position.position <= end:
                indexes[cdr_index].append(alignment_index)
                break
    return CdrIndices(tuple(indexes[0]), tuple(indexes[1]), tuple(indexes[2]))


def chain_family(value: str | None) -> Literal["heavy", "light"] | None:
    """Нормализует обозначение H/K/L либо именованной группы цепей."""

    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"h", "heavy", "vheavy", "vh", "vhh"}:
        return "heavy"
    if normalized in {"k", "l", "light", "vkappa", "vlambda", "vk", "vl"}:
        return "light"
    return None


def parse_numbering_label(value: str | int | None) -> ResidueNumber | None:
    """Разбирает номер вида ``27``, ``35A`` или ``H35A``."""

    if value is None:
        return None
    match = _POSITION_PATTERN.match(str(value).strip())
    if match is None:
        return None
    return ResidueNumber(position=int(match.group(1)), insertion=match.group(2).upper())


def _parse_long_rows(
    rows: Sequence[dict[str | None, str | None]],
    position_column: str,
    residue_column: str,
    insertion_column: str | None,
) -> list[ResidueNumber]:
    parsed: list[ResidueNumber] = []
    for row in rows:
        position = parse_numbering_label(row.get(position_column))
        residue = _clean_residue(row.get(residue_column))
        if position is None or not _is_residue(residue):
            continue
        insertion = _clean_insertion(row.get(insertion_column)) if insertion_column else position.insertion
        parsed.append(ResidueNumber(position.position, insertion, residue))
    return parsed


def _parse_wide_rows(
    headers: Sequence[str], rows: Sequence[dict[str | None, str | None]],
) -> list[ResidueNumber]:
    numbered_headers = [(header, parse_numbering_label(header)) for header in headers]
    numbered_headers = [(header, number) for header, number in numbered_headers if number is not None]
    if not numbered_headers:
        return []
    for row in rows:
        parsed: list[ResidueNumber] = []
        for header, number in numbered_headers:
            residue = _clean_residue(row.get(header))
            if _is_residue(residue):
                parsed.append(ResidueNumber(number.position, number.insertion, residue))
        if parsed:
            return parsed
    return []


def _boundaries_for_scheme(
    scheme: SchemeName, family: Literal["heavy", "light"] | None
) -> tuple[tuple[int, int], ...] | None:
    if scheme == "imgt":
        return _CDR_BOUNDARIES[scheme]["universal"]
    return _CDR_BOUNDARIES[scheme].get(family or "")


def _find_column(headers: Sequence[str], *candidates: str) -> str | None:
    normalized = {_normalize_header(header): header for header in headers}
    for candidate in candidates:
        match = normalized.get(_normalize_header(candidate))
        if match is not None:
            return match
    return None


def _first_nonempty(rows: Iterable[dict[str | None, str | None]], column: str) -> str | None:
    for row in rows:
        value = row.get(column)
        if value and value.strip():
            return value.strip()
    return None


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _clean_residue(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned if len(cleaned) == 1 else None


def _clean_insertion(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(character for character in value.strip().upper() if character.isalpha())


def _is_residue(value: str | None) -> bool:
    return value is not None and value not in _GAP_CHARACTERS
