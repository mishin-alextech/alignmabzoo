"""Подготовка и запуск Clustal Omega, а также сборка alignment.json."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from app.services.anarci_runner import CommandResult, job_child_path, validate_job_directory
from app.services.cdr_extract import (
    CHAIN_SCHEMES,
    CdrIndices,
    ParsedNumbering,
    ResidueNumber,
    build_alignment_numbering,
    cdr_indices_for_alignment,
)


CHAIN_GROUP_ORDER: tuple[str, ...] = ("VHeavy", "VHH", "VKappa", "VLambda", "Other")
_GROUP_PRIORITY = {group: index for index, group in enumerate(CHAIN_GROUP_ORDER)}
ALIGNMENT_BATCHES: dict[str, tuple[str, ...]] = {
    "vheavy": ("VHeavy", "VHH"),
    "vkappa": ("VKappa",),
    "vlambda": ("VLambda",),
}
_SAFE_MSA_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,30}$")


@dataclass(frozen=True, slots=True)
class AlignmentInput:
    """Одна последовательность, готовая к добавлению во входной FASTA MSA."""

    name: str
    sequence: str
    group: str
    animal_code: str


@dataclass(frozen=True, slots=True)
class ClustaloRunResult:
    """Результат Clustal Omega и пути обязательных артефактов job."""

    input_path: Path
    output_path: Path
    command_result: CommandResult | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Выравнивание создано без ошибки внешней команды."""

        return self.error is None and self.command_result is not None and self.command_result.succeeded


@dataclass(frozen=True, slots=True)
class ClustaloBatchResult:
    """Результат отдельного выравнивания родственных групп цепей."""

    batch_name: str
    records: tuple[AlignmentInput, ...]
    result: ClustaloRunResult


def sort_alignment_inputs(records: Sequence[AlignmentInput]) -> list[AlignmentInput]:
    """Сортирует MSA в обязательном порядке групп и затем по имени файла."""

    return sorted(records, key=lambda item: (_GROUP_PRIORITY.get(item.group, 3), item.name))


def write_alignment_input(
    records: Sequence[AlignmentInput],
    filename: str,
    *,
    job_directory: str | Path,
    jobs_root: str | Path,
) -> Path:
    """Создаёт входной FASTA одной группы выравнивания внутри job."""

    job_path = validate_job_directory(job_directory, jobs_root)
    alignment_directory = job_child_path(job_path, "alignment")
    alignment_directory.mkdir(parents=True, exist_ok=True)
    output_path = alignment_directory / filename
    lines: list[str] = []
    for record in sort_alignment_inputs(records):
        _validate_fasta_record(record)
        lines.extend((f">{msa_identifier(record.name)}", "".join(record.sequence.split()).upper()))
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output_path


def build_clustalo_command(input_path: str | Path, output_path: str | Path) -> tuple[str, ...]:
    """Строит команду Clustal Omega с жёстким ограничением в один поток."""

    return (
        "clustalo",
        "--infile",
        str(input_path),
        "--outfile",
        str(output_path),
        "--outfmt",
        "clu",
        "--threads",
        "1",
        "--force",
    )


def msa_identifier(sequence_name: str) -> str:
    """Возвращает устойчивый идентификатор для формата CLUSTAL.

    Короткие безопасные имена остаются читаемыми. Для длинных имён и имён с
    пробелами применяется короткий хеш: CLUSTAL не сокращает его, а viewer
    далее восстанавливает исходное имя из ``AlignmentInput``.
    """

    if _SAFE_MSA_IDENTIFIER.fullmatch(sequence_name):
        return sequence_name
    digest = hashlib.sha256(sequence_name.encode("utf-8")).hexdigest()[:20]
    return f"seq_{digest}"


def run_clustalo_batches(
    records: Sequence[AlignmentInput],
    *,
    job_directory: str | Path,
    jobs_root: str | Path,
) -> tuple[ClustaloBatchResult, ...]:
    """Создаёт три независимых MSA: VHeavy с VHH, VKappa и VLambda.

    Ошибка инструмента возвращается как данные, чтобы job-слой мог
    зафиксировать её в отчёте и логе. Функция не читает и не изменяет
    исходный data-root.
    """

    job_path = validate_job_directory(job_directory, jobs_root)
    results: list[ClustaloBatchResult] = []
    for batch_name, source_groups in ALIGNMENT_BATCHES.items():
        batch_records = tuple(record for record in records if record.group in source_groups)
        if not batch_records:
            continue
        input_path = write_alignment_input(
            batch_records,
            f"{batch_name}.fasta",
            job_directory=job_path,
            jobs_root=jobs_root,
        )
        output_path = job_child_path(job_path, "alignment", f"{batch_name}.aln")
        if shutil.which("clustalo") is None:
            result = ClustaloRunResult(
                input_path=input_path,
                output_path=output_path,
                command_result=None,
                error="Окружение обработки неисправно: не найдена команда clustalo.",
            )
        else:
            command = build_clustalo_command(input_path, output_path)
            command_result = _run_command(command, cwd=job_path)
            result = ClustaloRunResult(
                input_path=input_path,
                output_path=output_path,
                command_result=command_result,
                error=_clustalo_result_error(command_result, output_path),
            )
        results.append(ClustaloBatchResult(batch_name, batch_records, result))
    return tuple(results)


def parse_clustal_alignment(path: str | Path) -> dict[str, str]:
    """Читает CLUSTAL ``.aln`` в отображение имени на полную строку MSA."""

    source = Path(path)
    fragments: dict[str, list[str]] = {}
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"Не удалось прочитать выравнивание Clustal: {error}") from error

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("CLUSTAL"):
            continue
        if line[0].isspace():
            continue
        fields = stripped.split()
        if len(fields) < 2:
            continue
        name, fragment = fields[0], fields[1]
        if not _looks_like_alignment_fragment(fragment):
            continue
        fragments.setdefault(name, []).append(fragment)
    if not fragments:
        raise ValueError("Файл выравнивания Clustal не содержит последовательностей")
    return {name: "".join(parts) for name, parts in fragments.items()}


def build_alignment_document(
    records: Sequence[AlignmentInput],
    aligned_sequences: Mapping[str, str],
    numberings: Mapping[str, Mapping[str, ParsedNumbering | Sequence[ResidueNumber]]],
) -> dict[str, object]:
    """Собирает JSON viewer с нумерацией и CDR в координатах MSA.

    ``numberings`` содержит для каждого имени результаты трёх CSV ANARCI.
    Пропущенный или неразбираемый CSV даёт ``null`` для позиций нумерации и
    пустые CDR, а не некорректные координаты.
    """

    groups: dict[str, list[dict[str, object]]] = {group: [] for group in CHAIN_GROUP_ORDER}
    for record in sort_alignment_inputs(records):
        aligned = aligned_sequences.get(record.name) or aligned_sequences.get(msa_identifier(record.name))
        if aligned is None:
            raise ValueError(f"В Clustal-выравнивании отсутствует последовательность {record.name}")
        per_scheme = numberings.get(record.name, {})
        numbering_json: dict[str, list[str | None]] = {}
        cdr_json: dict[str, dict[str, list[int]]] = {}
        for scheme in CHAIN_SCHEMES:
            parsed = _as_parsed_numbering(per_scheme.get(scheme))
            numbering_json[scheme] = build_alignment_numbering(aligned, parsed.residues)
            cdr: CdrIndices = cdr_indices_for_alignment(
                aligned,
                parsed.residues,
                scheme,
                chain_group=record.group,
                chain_type=parsed.chain_type,
            )
            cdr_json[scheme] = cdr.as_dict()
        group = record.group if record.group in groups else "Other"
        groups[group].append(
            {
                "name": record.name,
                "seq": aligned,
                "numbering": numbering_json,
                "cdr": cdr_json,
            }
        )
    return {
        "groups": [
            {"name": group, "sequences": groups[group]}
            for group in CHAIN_GROUP_ORDER
        ]
    }


def write_alignment_document(
    document: Mapping[str, object],
    *,
    job_directory: str | Path,
    jobs_root: str | Path,
) -> Path:
    """Сохраняет ``alignment.json`` в корне изолированного каталога job."""

    job_path = validate_job_directory(job_directory, jobs_root)
    output_path = job_child_path(job_path, "alignment.json")
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _as_parsed_numbering(value: ParsedNumbering | Sequence[ResidueNumber] | None) -> ParsedNumbering:
    if value is None:
        return ParsedNumbering(())
    if isinstance(value, ParsedNumbering):
        return value
    return ParsedNumbering(tuple(value))


def _validate_fasta_record(record: AlignmentInput) -> None:
    if not record.name or "\n" in record.name or "\r" in record.name:
        raise ValueError("Имя последовательности для FASTA пустое или содержит перевод строки")
    sequence = "".join(record.sequence.split())
    if not sequence or not sequence.isascii() or not sequence.isalpha():
        raise ValueError(f"Последовательность {record.name} не подходит для Clustal Omega")


def _looks_like_alignment_fragment(value: str) -> bool:
    return bool(value) and all(character.isalpha() or character in {"-", ".", "*"} for character in value)


def _run_command(command: Sequence[str], *, cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return CommandResult(tuple(command), None, error=f"Не удалось запустить Clustal Omega: {error}")
    return CommandResult(
        tuple(command),
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _clustalo_result_error(result: CommandResult, output_path: Path) -> str | None:
    if result.error is not None:
        return result.error
    if result.returncode != 0:
        details = " ".join(result.stderr.split())[:500]
        return "Clustal Omega завершился с ошибкой" + (f": {details}" if details else "")
    if not output_path.is_file():
        return "Clustal Omega завершился без создания файла выравнивания"
    return None
