"""Повторное выравнивание сохранённого набора последовательностей."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.alignment import AlignmentInput, parse_clustal_alignment, run_clustalo_batches, write_alignment_document
from app.services.anarci_runner import job_child_path, validate_job_directory
from app.services.job_pipeline import _job_semaphore
from app.services.job_registry import JobRegistry, JobStatus


async def run_realignment(job_id: str, registry: JobRegistry) -> None:
    """Выполняет производную job под общим семафором вычислительных job."""

    async with _job_semaphore:
        await asyncio.to_thread(_run_realignment_sync, job_id, registry)


def schedule_realignment(job_id: str, registry: JobRegistry) -> asyncio.Task[None]:
    """Ставит производную job в ту же очередь, что и обычную обработку."""

    return asyncio.create_task(run_realignment(job_id, registry), name=f"alignmabzoo-realignment-{job_id}")


def _run_realignment_sync(job_id: str, registry: JobRegistry) -> None:
    record = registry.get(job_id)
    job_directory = registry.directory_for(job_id)
    report: dict[str, list[dict[str, str]]] = {"processed": [], "skipped": [], "errors": []}
    counts = {"files_found": 0, "files_processed": 0, "files_skipped": 0, "files_failed": 0, "sequences": 0}
    try:
        registry.update_status(job_id, JobStatus.RUNNING)
        parent_id = record.parent_job_id
        if not parent_id:
            raise ValueError("У производной job отсутствует родительская job.")
        parent_directory = registry.directory_for(parent_id)
        alignment = _read_json_artifact(parent_directory, "alignment.json")
        manifest = _read_json_artifact(parent_directory, "sequence_manifest.json")
        alignment_records = _alignment_records(alignment)
        manifest_records = {
            item.get("id"): item
            for item in manifest.get("sequences", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        selected_ids = tuple(record.sequence_ids)
        missing = [sequence_id for sequence_id in selected_ids if sequence_id not in alignment_records or sequence_id not in manifest_records]
        if missing:
            raise ValueError("Некоторые sequence_id отсутствуют в исходных артефактах job.")
        selected_records = [_make_alignment_input(alignment_records[sequence_id], manifest_records[sequence_id]) for sequence_id in selected_ids]
        if not selected_records:
            raise ValueError("Для повторного выравнивания не выбрано ни одной последовательности.")
        counts["sequences"] = len(selected_records)
        counts["files_processed"] = len(selected_records)
        aligned = _realign_records(selected_records, job_directory, registry.jobs_root, report)
        document = _build_realignment_document(selected_records, aligned, alignment_records)
        write_alignment_document(document, job_directory=job_directory, jobs_root=registry.jobs_root)
        _write_derived_fastas(selected_records, job_directory, registry.jobs_root)
        _copy_manifest(manifest, selected_ids, job_directory, registry.jobs_root)
        _write_report(job_directory, report)
        final_status = JobStatus.PARTIAL if report["errors"] or report["skipped"] else JobStatus.DONE
        registry.update_status(job_id, final_status, counts=counts)
    except Exception as error:
        report["errors"].append({"path": "job", "reason": str(error)})
        _write_report(job_directory, report)
        registry.update_status(job_id, JobStatus.FAILED, counts=counts, failure_reason=str(error))


def _read_json_artifact(directory: Path, name: str) -> dict[str, Any]:
    path = (directory / name).resolve()
    root = directory.resolve()
    if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError(f"Артефакт {name} исходной job недоступен.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Артефакт {name} содержит некорректный JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Артефакт {name} имеет недопустимый формат.")
    return value


def _alignment_records(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for group in document.get("groups", []):
        if not isinstance(group, dict):
            continue
        group_name = group.get("name")
        for sequence in group.get("sequences", []):
            if isinstance(sequence, dict) and isinstance(sequence.get("id"), str):
                result[sequence["id"]] = {**sequence, "group": group_name}
    return result


def _make_alignment_input(alignment: Mapping[str, Any], manifest: Mapping[str, Any]) -> AlignmentInput:
    protein = manifest.get("protein_sequence")
    if not isinstance(protein, str) or not protein:
        raise ValueError(f"Для sequence_id {alignment.get('id')} отсутствует сохранённый белок.")
    source = alignment.get("source") or manifest.get("source")
    if not isinstance(source, dict):
        source = {
            "animal": str(manifest.get("animal", "")),
            "project": str(manifest.get("project", "")),
            "group": str(manifest.get("group", "")),
            "relative_path": str(manifest.get("path", "")),
        }
    return AlignmentInput(
        id=str(alignment["id"]),
        name=str(manifest.get("new_name") or alignment.get("name") or alignment["id"]),
        sequence=protein,
        group=str(alignment.get("group") or manifest.get("chain_group") or "Other"),
        animal_code=str(source.get("animal", "")),
        source={str(key): str(value) for key, value in source.items()},
    )


def _realign_records(records: Sequence[AlignmentInput], job_directory: Path, jobs_root: Path, report: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    aligned: dict[str, str] = {}
    for batch in ("vheavy", "vkappa", "vlambda"):
        batch_records = tuple(record for record in records if record.group in {"VHeavy", "VHH"} if batch == "vheavy") if batch == "vheavy" else tuple(record for record in records if record.group == {"vkappa": "VKappa", "vlambda": "VLambda"}[batch])
        if not batch_records:
            continue
        if len(batch_records) == 1:
            aligned[batch_records[0].id] = batch_records[0].sequence
            continue
        result = next(item for item in run_clustalo_batches(batch_records, job_directory=job_directory, jobs_root=jobs_root) if item.batch_name == batch)
        if result.result is not None and result.result.succeeded:
            aligned.update(parse_clustal_alignment(result.result.output_path))
        else:
            report["errors"].append({"path": f"alignment/{batch}", "reason": result.result.error if result.result else "Clustal Omega не вернул результат."})
    other = tuple(record for record in records if record.group not in {"VHeavy", "VHH", "VKappa", "VLambda"})
    aligned.update({record.id: record.sequence for record in other})
    return aligned


def _build_realignment_document(records: Sequence[AlignmentInput], aligned: Mapping[str, str], old_records: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {"VHeavy": [], "VHH": [], "VKappa": [], "VLambda": [], "Other": []}
    for record in records:
        new_sequence = aligned.get(record.id)
        if new_sequence is None:
            continue
        old = old_records[record.id]
        numbering, cdr = _project_annotations(old, new_sequence)
        group = record.group if record.group in groups else "Other"
        groups[group].append({"id": record.id, "name": record.name, "seq": new_sequence, "source": dict(record.source), "numbering": numbering, "cdr": cdr})
    return {"groups": [{"name": name, "sequences": sequences} for name, sequences in groups.items()]}


def _project_annotations(old: Mapping[str, Any], new_sequence: str) -> tuple[dict[str, list[Any]], dict[str, dict[str, list[int]]]]:
    old_sequence = str(old.get("seq", ""))
    old_numbering = old.get("numbering") if isinstance(old.get("numbering"), dict) else {}
    old_cdr = old.get("cdr") if isinstance(old.get("cdr"), dict) else {}
    residue_numbering: dict[str, list[Any]] = {}
    residue_cdr: dict[str, set[int]] = {}
    for scheme in ("imgt", "kabat", "chothia"):
        values = old_numbering.get(scheme, [])
        cdr_values = old_cdr.get(scheme, {})
        cdr_indexes = {index for key in ("cdr1", "cdr2", "cdr3") for index in cdr_values.get(key, [])} if isinstance(cdr_values, dict) else set()
        ordinal = 0
        residue_numbering[scheme] = []
        residue_cdr[scheme] = set()
        for index, character in enumerate(old_sequence):
            if character in {"-", "."}:
                continue
            residue_numbering[scheme].append(values[index] if index < len(values) else None)
            if index in cdr_indexes:
                residue_cdr[scheme].add(ordinal)
            ordinal += 1
    numbering: dict[str, list[Any]] = {}
    cdr: dict[str, dict[str, list[int]]] = {}
    for scheme in ("imgt", "kabat", "chothia"):
        values = residue_numbering[scheme]
        numbering[scheme] = []
        cdr[scheme] = {"cdr1": [], "cdr2": [], "cdr3": []}
        ordinal = 0
        for index, character in enumerate(new_sequence):
            if character in {"-", "."}:
                numbering[scheme].append(None)
                continue
            numbering[scheme].append(values[ordinal] if ordinal < len(values) else None)
            for key in ("cdr1", "cdr2", "cdr3"):
                old_indexes = old_cdr.get(scheme, {}).get(key, []) if isinstance(old_cdr.get(scheme), dict) else []
                old_ordinals = _residue_ordinals(old_sequence, old_indexes)
                if ordinal in old_ordinals:
                    cdr[scheme][key].append(index)
            ordinal += 1
    return numbering, cdr


def _residue_ordinals(sequence: str, indexes: Sequence[int]) -> set[int]:
    wanted = set(indexes)
    return {ordinal for index, character in enumerate(sequence) if character not in {"-", "."} for ordinal in [sum(item not in {"-", "."} for item in sequence[:index])] if index in wanted}


def _copy_manifest(manifest: Mapping[str, Any], selected_ids: Sequence[str], directory: Path, jobs_root: Path) -> None:
    selected = set(selected_ids)
    records = [item for item in manifest.get("sequences", []) if isinstance(item, dict) and item.get("id") in selected]
    job_child_path(directory, "sequence_manifest.json").write_text(json.dumps({"sequences": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_derived_fastas(records: Sequence[AlignmentInput], directory: Path, jobs_root: Path) -> None:
    """Сохраняет выбранный белковый набор для самостоятельного открытия job."""

    lines = [part for record in records for part in (f">{record.id}", record.sequence)]
    job_child_path(directory, "chains_named.fasta").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_report(directory: Path, report: Mapping[str, Any]) -> None:
    job_child_path(directory, "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")