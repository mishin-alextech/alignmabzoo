"""Оркестрация изолированного конвейера обработки одной job."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.config import get_settings
from app.services.alignment import (
    AlignmentInput,
    build_alignment_document,
    parse_clustal_alignment,
    run_clustalo_batches,
    write_alignment_document,
)
from app.services.anarci_runner import (
    check_runtime_environment,
    job_child_path,
    run_anarci_for_records,
)
from app.services.cdr_extract import parse_anarci_csv_records
from app.services.discovery import DiscoveryService, get_discovery_service
from app.services.job_registry import JobCounts, JobRecord, JobRegistry, JobStatus
from app.services.naming import name_chain
from app.services.parser import SUPPORTED_SUFFIXES, parse_sequence_file


MAX_CONCURRENT_JOBS = min(2, max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "2"))))
_job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


@dataclass(frozen=True, slots=True)
class SelectedGroup:
    """Одна проверенная группа исходных данных для job."""

    animal_code: str
    project_name: str
    group_name: str
    directory: Path


class SelectionError(ValueError):
    """Выбор пользователя не соответствует read-only дереву исходных данных."""


def validate_selection(selection: Mapping[str, Any], discovery: DiscoveryService) -> tuple[SelectedGroup, ...]:
    """Проверяет JSON выбора и возвращает только доступные каталоги групп."""

    animals = selection.get("animals")
    if not isinstance(animals, list) or not animals:
        raise SelectionError("Необходимо выбрать хотя бы одно животное.")
    data_root = Path(getattr(discovery, "_data_root", get_settings().data_root))
    selected: list[SelectedGroup] = []
    seen: set[tuple[str, str, str]] = set()
    for animal in animals:
        if not isinstance(animal, dict) or not isinstance(animal.get("code"), str):
            raise SelectionError("Выбор животного имеет недопустимый формат.")
        code = animal["code"]
        if not discovery.is_known_animal(code):
            raise SelectionError(f"Код животного «{code}» не поддерживается.")
        projects = animal.get("projects")
        if not isinstance(projects, list) or not projects:
            raise SelectionError(f"Для животного «{code}» не выбраны проекты.")
        for project in projects:
            if not isinstance(project, dict) or not isinstance(project.get("name"), str):
                raise SelectionError("Выбор проекта имеет недопустимый формат.")
            project_name = project["name"]
            if not discovery.has_project(code, project_name):
                raise SelectionError(f"Проект «{project_name}» для животного «{code}» не найден.")
            groups = project.get("groups")
            if not isinstance(groups, list) or not groups or not all(isinstance(item, str) for item in groups):
                raise SelectionError(f"Для проекта «{project_name}» не выбраны группы.")
            available = discovery.list_groups(code, project_name)
            names = available if "all" in groups else tuple(groups)
            if not names:
                raise SelectionError(f"В проекте «{project_name}» нет доступных групп.")
            for group_name in names:
                if group_name not in available:
                    raise SelectionError(f"Группа «{group_name}» в проекте «{project_name}» не найдена.")
                key = (code, project_name, group_name)
                if key not in seen:
                    seen.add(key)
                    selected.append(SelectedGroup(code, project_name, group_name, data_root / discovery.animal_directory_name(code) / project_name / group_name))
    return tuple(selected)


def schedule_job(job: JobRecord, registry: JobRegistry, discovery: DiscoveryService | None = None) -> asyncio.Task[None]:
    """Ставит job в локальную очередь выполнения, ограниченную двумя задачами."""

    return asyncio.create_task(run_job(job.id, registry, discovery), name=f"alignmabzoo-job-{job.id}")


async def run_job(job_id: str, registry: JobRegistry, discovery: DiscoveryService | None = None) -> None:
    """Выполняет job, не блокируя event loop синхронными парсерами и утилитами."""

    async with _job_semaphore:
        await asyncio.to_thread(_run_job_sync, job_id, registry, discovery or get_discovery_service())


def _run_job_sync(job_id: str, registry: JobRegistry, discovery: DiscoveryService) -> None:
    record = registry.get(job_id)
    job_directory = registry.directory_for(job_id)
    report: dict[str, list[dict[str, str]]] = {
        "processed": [],
        "skipped": [],
        "clustalo_exclusions": [],
        "errors": [],
    }
    counts = {"files_found": 0, "files_processed": 0, "files_skipped": 0, "files_failed": 0, "sequences": 0}
    try:
        registry.update_status(job_id, JobStatus.RUNNING)
        _append_log(job_directory, "Job запущена.")
        job_child_path(job_directory, "log_valid_error.txt").touch(exist_ok=True)
        runtime = check_runtime_environment()
        if not runtime.is_available:
            raise RuntimeError(runtime.error or "Окружение обработки неисправно.")
        selected = validate_selection(record.selection.root, discovery)
        selected_animals = tuple(dict.fromkeys(item.animal_code for item in selected))
        include_animal_code = len(selected_animals) > 1
        source_files = list(_discover_files(selected))
        counts["files_found"] = len(source_files)
        _append_log(job_directory, f"Найдено входных файлов: {len(source_files)}.")
        parsed_records: list[AlignmentInput] = []
        parsed_paths: dict[str, str] = {}
        used_names: set[str] = set()
        for selected_group, source_path in source_files:
            result = parse_sequence_file(source_path)
            relative = _report_path(selected_group, source_path)
            if not result.is_success or result.sequence is None:
                reason = result.error or "Не удалось извлечь белковую последовательность."
                report["errors"].append({"path": relative, "reason": reason})
                counts["files_failed"] += 1
                _append_log(job_directory, f"Ошибка файла {relative}: {reason}")
                continue
            sequence = _normalize_protein_sequence(result.sequence)
            if sequence is None:
                reason = (
                    "Белковая последовательность содержит недопустимые символы "
                    "после удаления пробелов и нормализации регистра."
                )
                report["errors"].append({"path": relative, "reason": reason})
                counts["files_failed"] += 1
                _append_log(job_directory, f"Ошибка файла {relative}: {reason}")
                continue
            named = name_chain(selected_group.animal_code, selected_group.project_name, result.filename)
            base_name = (
                f"{named.group}_{selected_group.animal_code}_{named.clone}"
                if include_animal_code
                else named.name
            )
            sequence_name = _unique_name(base_name, used_names)
            if sequence_name != base_name:
                _append_log(job_directory, f"Переименование {relative}: {base_name} → {sequence_name}.")
            else:
                _append_log(job_directory, f"Переименование {relative}: {sequence_name}.")
            if named.diagnostic:
                _append_naming_error(job_directory, f"{relative}: {named.diagnostic}")
            parsed_records.append(AlignmentInput(sequence_name, sequence, named.group, selected_group.animal_code))
            parsed_paths[sequence_name] = relative
            report["processed"].append({"path": relative, "name": sequence_name})
            counts["files_processed"] += 1
        _write_parsed_fasta(job_directory, parsed_records, parsed_paths)
        _write_named_fasta(job_directory, parsed_records)
        counts["sequences"] = len(parsed_records)
        numberings: dict[str, dict[str, object]] = {item.name: {} for item in parsed_records}
        if parsed_records:
            anarci_results = run_anarci_for_records(
                input_fasta=job_child_path(job_directory, "chains_named.fasta"),
                selected_animals=selected_animals,
                job_directory=job_directory,
                jobs_root=registry.jobs_root,
            )
            for scheme_result in anarci_results:
                _log_command(job_directory, scheme_result.command_result)
                if scheme_result.succeeded:
                    parsed_by_name = parse_anarci_csv_records(scheme_result.output_path)
                    for item in parsed_records:
                        parsed = parsed_by_name.get(item.name)
                        if parsed is not None:
                            numberings[item.name][scheme_result.scheme] = parsed
                        else:
                            reason = "В общем CSV ANARCI отсутствует нумерация последовательности."
                            report["errors"].append({"path": item.name, "reason": f"ANARCI {scheme_result.scheme}: {reason}"})
                            _append_log(job_directory, f"Ошибка ANARCI для {item.name}: {reason}")
                else:
                    reason = scheme_result.error or "Непредвиденная ошибка ANARCI."
                    report["errors"].append({"path": "ANARCI", "reason": f"ANARCI {scheme_result.scheme}: {reason}"})
                    _append_log(job_directory, f"Ошибка ANARCI для схемы {scheme_result.scheme}: {reason}")
        if parsed_records:
            aligned_records: list[AlignmentInput] = []
            aligned: dict[str, str] = {}
            for batch in run_clustalo_batches(parsed_records, job_directory=job_directory, jobs_root=registry.jobs_root):
                for command_result in batch.command_results:
                    _log_command(job_directory, command_result)
                for exclusion in batch.exclusions:
                    reason = f"Не прошедшие Clustal Omega: {exclusion.reason}"
                    report["clustalo_exclusions"].append(
                        {
                            "path": parsed_paths.get(exclusion.record.name, exclusion.record.name),
                            "reason": reason,
                        }
                    )
                    counts["files_skipped"] += 1
                    _append_log(job_directory, f"{reason} Исключена последовательность {exclusion.record.name}.")
                if batch.result is not None and batch.result.succeeded:
                    aligned.update(parse_clustal_alignment(batch.result.output_path))
                    aligned_records.extend(batch.records)
                elif batch.result is not None:
                    reason = batch.result.error or "Непредвиденная ошибка Clustal Omega."
                    report["errors"].append({"path": f"alignment/{batch.batch_name}", "reason": reason})
                    _append_log(job_directory, f"Ошибка выравнивания {batch.batch_name}: {reason}")
            if aligned_records:
                document = build_alignment_document(aligned_records, aligned, numberings)
                write_alignment_document(document, job_directory=job_directory, jobs_root=registry.jobs_root)
        else:
            report["skipped"].append({"path": "job", "reason": "Не найдено пригодных последовательностей для выравнивания."})
            counts["files_skipped"] += 1
        _write_report(job_directory, report)
        final_status = (
            JobStatus.PARTIAL
            if report["errors"] or report["skipped"] or report["clustalo_exclusions"]
            else JobStatus.DONE
        )
        registry.update_status(job_id, final_status, counts=JobCounts(**counts))
        _append_log(job_directory, f"Job завершена со статусом {final_status.value}.")
    except Exception as error:
        _append_log(job_directory, f"Критическая ошибка job: {error}")
        report["errors"].append({"path": "job", "reason": str(error)})
        _write_report(job_directory, report)
        try:
            registry.update_status(job_id, JobStatus.FAILED, counts=JobCounts(**counts), failure_reason=str(error))
        except Exception:
            pass


def _discover_files(groups: Iterable[SelectedGroup]) -> Iterable[tuple[SelectedGroup, Path]]:
    for selected in groups:
        try:
            for root, directories, filenames in os.walk(selected.directory, followlinks=False):
                directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
                for filename in sorted(filenames):
                    path = Path(root) / filename
                    if not path.is_symlink() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                        yield selected, path
        except OSError:
            continue


def _report_path(selected: SelectedGroup, source: Path) -> str:
    return f"{selected.project_name}/{selected.group_name}/{source.name}"


def _unique_name(value: str, used: set[str]) -> str:
    candidate, index = value, 2
    while candidate in used:
        candidate = f"{value}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _normalize_protein_sequence(sequence: str) -> str | None:
    """Удаляет пробелы и отклоняет символы, недопустимые во входном FASTA."""

    normalized = "".join(sequence.split()).upper()
    if not normalized or not normalized.isascii() or not normalized.isalpha():
        return None
    return normalized


def _write_parsed_fasta(directory: Path, records: list[AlignmentInput], paths: Mapping[str, str]) -> None:
    """Записывает извлечённые цепи с исходным путём проекта и группы в FASTA-заголовке."""

    lines: list[str] = []
    for item in records:
        lines.extend((f">{paths[item.name]}", item.sequence))
    job_child_path(directory, "parsed_chains.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_named_fasta(directory: Path, records: list[AlignmentInput]) -> None:
    lines: list[str] = []
    for item in records:
        lines.extend((f">{item.name}", item.sequence))
    job_child_path(directory, "chains_named.fasta").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _append_log(directory: Path, message: str) -> None:
    with job_child_path(directory, "log.txt").open("a", encoding="utf-8") as output:
        output.write(message.rstrip() + "\n")


def _append_naming_error(directory: Path, message: str) -> None:
    with job_child_path(directory, "log_valid_error.txt").open("a", encoding="utf-8") as output:
        output.write(message.rstrip() + "\n")


def _log_command(directory: Path, result: object) -> None:
    if result is None:
        return
    command = getattr(result, "command", ())
    returncode = getattr(result, "returncode", None)
    error = getattr(result, "error", None)
    _append_log(directory, f"Команда: {' '.join(command)}; код возврата: {returncode}; ошибка: {error or 'нет'}.")


def _write_report(directory: Path, report: Mapping[str, object]) -> None:
    job_child_path(directory, "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
