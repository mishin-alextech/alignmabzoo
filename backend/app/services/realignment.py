"""Повторное выравнивание сохранённых белков без чтения исходных файлов."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.alignment import AlignmentInput, msa_identifier, parse_clustal_alignment, run_clustalo_batches, validate_sequence_ids, write_alignment_document
from app.services.anarci_runner import check_runtime_environment, job_child_path, validate_job_directory
from app.services.job_pipeline import _job_semaphore
from app.services.job_registry import JobRegistry, JobStatus, retain_job_task


async def run_realignment(job_id: str, registry: JobRegistry) -> None:
    """Использует общий с обычными job лимит вычислений."""

    async with _job_semaphore:
        await asyncio.to_thread(_run_realignment_sync, job_id, registry)


def schedule_realignment(job_id: str, registry: JobRegistry) -> asyncio.Task[None]:
    """Сохраняет задачу в памяти до завершения обработки."""

    return retain_job_task(asyncio.create_task(run_realignment(job_id, registry), name=f"alignmabzoo-realignment-{job_id}"))


def alignment_records(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Добавляет старым JSON те же ID, что normalizeViewerAlignment на клиенте."""

    result: dict[str, dict[str, Any]] = {}
    groups = document.get("groups", [])
    if not isinstance(groups, list):
        raise ValueError("Список групп выравнивания имеет недопустимый формат.")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str):
            raise ValueError("Группа выравнивания имеет недопустимый формат.")
        occurrences: dict[str, int] = {}
        for sequence in group.get("sequences", []):
            if not isinstance(sequence, dict) or not isinstance(sequence.get("name"), str):
                raise ValueError("Последовательность выравнивания имеет недопустимый формат.")
            name = sequence["name"]
            occurrence = occurrences.get(name, 0)
            occurrences[name] = occurrence + 1
            sequence_id = sequence.get("id") or "legacy:" + json.dumps([group["name"], name, occurrence], ensure_ascii=False, separators=(",", ":"))
            if not isinstance(sequence_id, str) or sequence_id in result:
                raise ValueError("Идентификаторы последовательностей должны быть строками без повторов.")
            result[sequence_id] = {**sequence, "id": sequence_id, "group": group["name"]}
    return result


def _run_realignment_sync(job_id: str, registry: JobRegistry) -> None:
    report: dict[str, list[dict[str, str]]] = {
        "processed": [], "skipped": [], "errors": [], "clustalo_exclusions": [], "user_exclusions": [],
    }
    counts = {"files_found": 0, "files_processed": 0, "files_skipped": 0, "files_failed": 0, "sequences": 0}
    record = None
    directory: Path | None = None
    try:
        record = registry.get(job_id)
        directory = validate_job_directory(registry.directory_for(job_id), registry.jobs_root)
        registry.update_status(job_id, JobStatus.RUNNING)
        _append_log(directory, "Повторное выравнивание запущено.")
        job_child_path(directory, "log_valid_error.txt").touch(exist_ok=True)
        runtime = check_runtime_environment()
        if not runtime.is_available:
            raise ValueError(runtime.error or "Окружение обработки неисправно.")
        if not record.parent_job_id:
            raise ValueError("У производной job отсутствует родительская job.")
        parent_directory = validate_job_directory(registry.directory_for(record.parent_job_id), registry.jobs_root)
        old_records = alignment_records(_read_json_artifact(parent_directory, "alignment.json"))
        manifest_path = job_child_path(parent_directory, "sequence_manifest.json")
        manifest = _read_json_artifact(parent_directory, "sequence_manifest.json") if manifest_path.exists() else {"sequences": []}
        manifest_records = {}
        for item in manifest.get("sequences", []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("Manifest содержит запись без идентификатора.")
            if item["id"] in manifest_records:
                raise ValueError("Manifest содержит повторяющиеся идентификаторы.")
            manifest_records[item["id"]] = item
        selected_ids = set(record.sequence_ids)
        if not selected_ids or not selected_ids.issubset(old_records):
            raise ValueError("Выбранные ID отсутствуют в родительском выравнивании либо набор пуст.")
        counts["files_found"] = len(record.sequence_ids)
        _append_log(directory, f"Выбрано последовательностей: {len(selected_ids)}; родительская job: {record.parent_job_id}.")
        for sequence_id, old in old_records.items():
            if sequence_id not in selected_ids:
                report["user_exclusions"].append(_report_entry(old, "Исключено пользователем при повторном выравнивании."))
        records: list[AlignmentInput] = []
        for sequence_id in record.sequence_ids:
            old = old_records[sequence_id]
            try:
                if manifest_path.exists() and sequence_id not in manifest_records:
                    raise ValueError("Запись последовательности отсутствует в сохранённом manifest.")
                records.append(_make_alignment_input(old, manifest_records.get(sequence_id)))
            except ValueError as error:
                report["errors"].append(_report_entry(old, str(error)))
                counts["files_failed"] += 1
                _append_log(directory, f"Ошибка последовательности {old['name']}: {error}")
        aligned = _realign_records(records, directory, registry.jobs_root, report)
        successful: list[AlignmentInput] = []
        for item in records:
            sequence = aligned.get(item.id)
            if sequence is not None and _ungap(sequence) == item.sequence:
                successful.append(item)
                report["processed"].append({"id": item.id, "name": item.name, "path": item.source.get("relative_path", item.name)})
            elif sequence is not None:
                report["errors"].append({"id": item.id, "path": item.name, "reason": "Clustal Omega изменил белковую последовательность."})
        counts["sequences"] = counts["files_processed"] = len(successful)
        counts["files_skipped"] = len(report["clustalo_exclusions"])
        counts["files_failed"] = counts["files_found"] - counts["files_processed"] - counts["files_skipped"]
        if not successful:
            raise ValueError("Повторное выравнивание не создало ни одной пригодной последовательности. Исходный результат сохранён.")
        document = _build_realignment_document(successful, aligned, old_records)
        write_alignment_document(document, job_directory=directory, jobs_root=registry.jobs_root)
        _write_derived_artifacts(successful, manifest_records, directory)
        _write_report(directory, report)
        final_status = JobStatus.PARTIAL if report["errors"] or report["clustalo_exclusions"] else JobStatus.DONE
        _append_log(directory, f"Повторное выравнивание завершено: {final_status.value}; последовательностей: {len(successful)}.")
        registry.update_status(job_id, final_status, counts=counts)
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) else f"Не удалось выполнить повторное выравнивание: {error}"
        report["errors"].append({"path": "job", "reason": reason})
        if directory is not None:
            try:
                _append_log(directory, reason)
                _write_report(directory, report)
            except OSError:
                # Каталог job уже не безопасен для записи; статус всё равно надо сохранить.
                pass
        if record is not None:
            registry.update_status(job_id, JobStatus.FAILED, counts=counts, failure_reason=reason)


def _read_json_artifact(directory: Path, name: str) -> dict[str, Any]:
    path = job_child_path(directory, name)
    if not path.is_file():
        raise ValueError(f"Артефакт {name} исходной job недоступен.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Артефакт {name} не удалось прочитать как JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Артефакт {name} имеет недопустимый формат.")
    return value


def _ungap(sequence: str) -> str:
    return sequence.replace("-", "").replace(".", "").upper()


def _make_alignment_input(old: Mapping[str, Any], manifest: Mapping[str, Any] | None) -> AlignmentInput:
    old_sequence = old.get("seq")
    if not isinstance(old_sequence, str) or not _ungap(old_sequence):
        raise ValueError("Отсутствует сохранённая белковая последовательность.")
    protein = _ungap(old_sequence)
    if manifest is not None and manifest.get("protein_sequence") != protein:
        raise ValueError("Сохранённый белок manifest не совпадает с родительским выравниванием.")
    source = old.get("source") or (manifest or {}).get("source")
    if not source and manifest and all(isinstance(manifest.get(key), str) for key in ("animal", "project", "group", "path")):
        source = {"animal": manifest["animal"], "project": manifest["project"], "group": manifest["group"], "relative_path": manifest["path"]}
    source = {key: value for key, value in source.items() if isinstance(key, str) and isinstance(value, str)} if isinstance(source, dict) else {}
    return AlignmentInput(id=str(old["id"]), name=str(old["name"]), sequence=protein, group=str(old["group"]), animal_code=source.get("animal", ""), source=source)


def _report_entry(record: Mapping[str, Any], reason: str) -> dict[str, str]:
    source = record.get("source")
    path = source.get("relative_path") if isinstance(source, dict) else None
    return {"id": str(record["id"]), "path": str(path or record["name"]), "reason": reason}


def _realign_records(records: Sequence[AlignmentInput], directory: Path, jobs_root: Path, report: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    aligned: dict[str, str] = {}
    validate_sequence_ids(records)
    by_tool_id = {msa_identifier(record.id): record for record in records}
    for batch in run_clustalo_batches(records, job_directory=directory, jobs_root=jobs_root):
        for command in batch.command_results:
            _append_log(directory, f"Команда: {' '.join(command.command)}; код возврата: {command.returncode}; ошибка: {command.error or 'нет'}.")
            for stream in ("stdout", "stderr"):
                output = getattr(command, stream, "")
                if output:
                    _append_log(directory, f"Вывод команды ({stream}):\n{output}")
        for exclusion in batch.exclusions:
            record = exclusion.record
            entry = {"id": record.id, "path": record.source.get("relative_path", record.name), "reason": exclusion.reason}
            report["clustalo_exclusions"].append(entry)
            _append_log(directory, f"Исключена последовательность {record.name}: {exclusion.reason}")
        if batch.result is None or not batch.result.succeeded:
            reason = batch.result.error if batch.result else "Clustal Omega не создал выравнивание пакета."
            report["errors"].append({"path": f"alignment/{batch.batch_name}", "reason": reason or "Неизвестная ошибка выравнивания."})
            _append_log(directory, f"Ошибка пакета {batch.batch_name}: {reason}")
            continue
        output = parse_clustal_alignment(batch.result.output_path)
        if set(output) != {msa_identifier(record.id) for record in batch.records}:
            raise ValueError("Набор последовательностей в выходном MSA не совпадает с ожидаемым.")
        aligned.update({by_tool_id[identifier].id: sequence for identifier, sequence in output.items() if identifier in by_tool_id})
        _append_log(directory, f"Пакет {batch.batch_name}: сохранено последовательностей {len(output)}.")
    return aligned


def _project_annotations(old: Mapping[str, Any], new_sequence: str) -> tuple[dict[str, list[Any]], dict[str, dict[str, list[int]]]]:
    """Переносит каждую аннотацию через порядковый номер остатка за линейное время."""

    old_sequence = str(old.get("seq", ""))
    if _ungap(old_sequence) != _ungap(new_sequence):
        raise ValueError("Нельзя перенести аннотации: белковая последовательность изменилась.")
    old_columns = [index for index, residue in enumerate(old_sequence) if residue not in "-."]
    new_columns = [index for index, residue in enumerate(new_sequence) if residue not in "-."]
    projection = dict(zip(old_columns, new_columns))
    old_numbering = old.get("numbering") or {}
    old_cdr = old.get("cdr") or {}
    numbering: dict[str, list[Any]] = {}
    cdr: dict[str, dict[str, list[int]]] = {}
    for scheme in ("imgt", "kabat", "chothia"):
        values = old_numbering.get(scheme, [])
        numbering[scheme] = [None] * len(new_sequence)
        for old_index, new_index in projection.items():
            numbering[scheme][new_index] = values[old_index] if old_index < len(values) else None
        scheme_cdr = old_cdr.get(scheme) or {}
        cdr[scheme] = {key: sorted({projection[index] for index in scheme_cdr.get(key, []) if index in projection}) for key in ("cdr1", "cdr2", "cdr3")}
    return numbering, cdr


def _build_realignment_document(records: Sequence[AlignmentInput], aligned: Mapping[str, str], old_records: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in ("VHeavy", "VHH", "VKappa", "VLambda", "Other")}
    for record in records:
        numbering, cdr = _project_annotations(old_records[record.id], aligned[record.id])
        row = {"id": record.id, "name": record.name, "seq": aligned[record.id], "numbering": numbering, "cdr": cdr}
        if record.source:
            row["source"] = dict(record.source)
        groups.get(record.group, groups["Other"]).append(row)
    for rows in groups.values():
        if not rows:
            continue
        width = len(rows[0]["seq"])
        if any(len(row["seq"]) != width for row in rows):
            raise ValueError("Длины строк MSA в одной панели не совпадают.")
        columns = [index for index in range(width) if any(row["seq"][index] not in "-." for row in rows)]
        projection = {old: new for new, old in enumerate(columns)}
        for row in rows:
            row["seq"] = "".join(row["seq"][index] for index in columns)
            for scheme in ("imgt", "kabat", "chothia"):
                row["numbering"][scheme] = [row["numbering"][scheme][index] for index in columns]
                row["cdr"][scheme] = {key: [projection[index] for index in indexes if index in projection] for key, indexes in row["cdr"][scheme].items()}
    return {"groups": [{"name": name, "sequences": rows} for name, rows in groups.items()]}


def _write_derived_artifacts(records: Sequence[AlignmentInput], manifest: Mapping[str, Mapping[str, Any]], directory: Path) -> None:
    """Сохраняет самостоятельный manifest; отсутствующее происхождение не угадывает."""

    entries = []
    fasta = []
    parsed = []
    nucleotides = []
    for record in records:
        entry = {**manifest.get(record.id, {}), "id": record.id, "msa_id": msa_identifier(record.id), "new_name": record.name, "protein_sequence": record.sequence, "chain_group": record.group}
        if record.source:
            entry["source"] = dict(record.source)
        entries.append(entry)
        fasta.extend((f">{msa_identifier(record.id)} {record.name}", record.sequence))
        if all(record.source.get(key) for key in ("project", "group", "relative_path")):
            filename = record.source["relative_path"].replace("\\", "/").rsplit("/", 1)[-1]
            parsed_name = f"{record.source['project']}/{record.source['group']}/{filename}"
        else:
            parsed_name = record.name
        parsed.extend((f">{parsed_name}", record.sequence))
        nucleotide = entry.get("nucleotide_sequence")
        if isinstance(nucleotide, str) and nucleotide:
            nucleotides.extend((f">{msa_identifier(record.id)}", nucleotide))
    for name, lines in (("chains_named.fasta", fasta), ("parsed_chains.txt", parsed), ("parsed_chains_nucleotide.txt", nucleotides)):
        job_child_path(directory, name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    job_child_path(directory, "sequence_manifest.json").write_text(json.dumps({"sequences": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_log(directory: Path, message: str) -> None:
    with job_child_path(directory, "log.txt").open("a", encoding="utf-8") as output:
        output.write(message + "\n")


def _write_report(directory: Path, report: Mapping[str, Any]) -> None:
    job_child_path(directory, "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
