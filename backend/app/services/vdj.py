"""Локальный V(D)J-анализ сохранённых нуклеотидных доменов через IgBLAST."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.anarci_runner import job_child_path, validate_job_directory
from app.services.job_pipeline import _job_semaphore
from app.services.job_registry import JobCounts, JobRegistry, JobStatus, retain_job_task

PROFILE_ROOT = Path("/opt/igblast/profiles")
IGBLAST_ROOT = Path("/opt/igblast")
SUPPORTED_ANIMALS = frozenset({"Hu", "Ms", "Rb", "Rt", "Pg", "Ov", "Gt", "Bv"})


def schedule_vdj(job_id: str, registry: JobRegistry) -> asyncio.Task[None]:
    """Сохраняет задачу V(D)J в памяти приложения до завершения."""
    task = asyncio.create_task(run_vdj(job_id, registry), name=f"alignmabzoo-vdj-{job_id}")
    return retain_job_task(task)


async def run_vdj(job_id: str, registry: JobRegistry) -> None:
    """Выполняет V(D)J-анализ под общим лимитом вычислительных job."""
    async with _job_semaphore:
        await asyncio.to_thread(_run_vdj_sync, job_id, registry)


def _run_vdj_sync(job_id: str, registry: JobRegistry) -> None:
    report: dict[str, list[dict[str, str]]] = {"processed": [], "skipped": [], "errors": []}
    counts = JobCounts()
    record = None
    directory: Path | None = None
    try:
        record = registry.get(job_id)
        directory = validate_job_directory(registry.directory_for(job_id), registry.jobs_root)
        registry.update_status(job_id, JobStatus.RUNNING)
        _log(directory, "V(D)J-анализ запущен.")
        if not record.parent_job_id:
            raise ValueError("У V(D)J-job отсутствует родительская job.")
        parent = validate_job_directory(registry.directory_for(record.parent_job_id), registry.jobs_root)
        manifest = _read_json(job_child_path(parent, "sequence_manifest.json"), "sequence_manifest.json")
        selected = tuple(record.sequence_ids)
        entries = _manifest_entries(manifest, selected)
        _write_input(directory, entries)
        results = [_unavailable(item["id"], "Последовательность не содержит сохранённой ДНК.") for item in entries if not item.get("nucleotide_sequence")]
        candidates = [item for item in entries if item.get("nucleotide_sequence")]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in candidates:
            animal = item.get("animal")
            if not isinstance(animal, str) or animal not in SUPPORTED_ANIMALS:
                results.append(_unavailable(item["id"], "Для животного пока нет готового собственного профиля IMGT."))
                continue
            grouped[animal].append(item)
        commands: list[dict[str, Any]] = []
        for animal, items in grouped.items():
            profile, reason = _load_profile(animal)
            if profile is None:
                results.extend(_unavailable(item["id"], reason) for item in items)
                continue
            if shutil.which("igblastn") is None:
                results.extend(_unavailable(item["id"], "IgBLAST не установлен в образе dev-сервиса.", profile) for item in items)
                continue
            supported_chain_groups = profile.get("chain_groups")
            profile_items = items
            if isinstance(supported_chain_groups, list):
                supported = set(supported_chain_groups)
                profile_items = [item for item in items if item.get("chain_group") in supported]
                results.extend(
                    _unavailable(item["id"], "Профиль IMGT не содержит базу для этого типа цепи.", profile)
                    for item in items
                    if item.get("chain_group") not in supported
                )
            if not profile_items:
                continue
            rows, detailed_reports, profile_commands = _run_profile(directory, animal, profile_items, profile)
            commands.extend(profile_commands)
            failed_command = next((command for command in profile_commands if command["returncode"] != 0), None)
            if failed_command is not None:
                detail = " ".join(str(failed_command.get("stderr", "")).split())[:500]
                reason = "IgBLAST завершился с ошибкой" + (f": {detail}" if detail else "")
                results.extend(_failed(item["id"], reason, profile) for item in profile_items)
                continue
            for item in profile_items:
                row = rows.get(item["id"])
                if row is None:
                    results.append(_ambiguous(item["id"], "IgBLAST не вернул строку AIRR для последовательности.", profile))
                elif item["id"] not in detailed_reports:
                    results.append(_failed(item["id"], "IgBLAST не вернул подробный отчёт для последовательности.", profile))
                else:
                    results.append(_result_from_airr(item["id"], row, detailed_reports[item["id"]], profile))
        ordered = _order_results(results, selected)
        _write_result(directory, record.parent_job_id, ordered, commands)
        for item in ordered:
            target = report["processed"] if item["status"] == "ready" else report["skipped"]
            target.append({"id": item["sequence_id"], "reason": item.get("reason") or ""})
        _write_json(job_child_path(directory, "report.json"), report)
        ready = sum(item["status"] == "ready" for item in ordered)
        counts = JobCounts(files_found=len(selected), files_processed=ready, files_skipped=len(selected)-ready, sequences=ready)
        status = JobStatus.DONE if ready == len(selected) else JobStatus.PARTIAL
        _log(directory, f"V(D)J-анализ завершён: {status.value}; обработано: {ready}.")
        registry.update_status(job_id, status, counts=counts)
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) else f"Не удалось выполнить V(D)J-анализ: {error}"
        report["errors"].append({"path": "job", "reason": reason})
        if directory is not None:
            try:
                _log(directory, reason)
                _write_json(job_child_path(directory, "report.json"), report)
                _write_result(directory, record.parent_job_id if record else None, [], [])
            except OSError:
                pass
        if record is not None:
            registry.update_status(job_id, JobStatus.FAILED, counts=counts, failure_reason=reason)


def _manifest_entries(document: Mapping[str, Any], selected: Sequence[str]) -> list[dict[str, Any]]:
    raw = document.get("sequences")
    if not isinstance(raw, list):
        raise ValueError("Manifest V(D)J не содержит списка последовательностей.")
    records: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Manifest содержит запись без stable ID.")
        if item["id"] in records:
            raise ValueError("Manifest содержит повторяющиеся stable ID.")
        records[item["id"]] = item
    if not selected or not set(selected).issubset(records):
        raise ValueError("Выбранные stable ID отсутствуют в manifest родительской job.")
    return [records[item] for item in selected]


def _write_input(directory: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    lines: list[str] = []
    for entry in entries:
        sequence = entry.get("nucleotide_sequence")
        if isinstance(sequence, str) and _valid_dna(sequence):
            lines.extend((f">{entry['id']}", _normalise_dna(sequence)))
    job_child_path(directory, "vdj", "input.fasta").parent.mkdir(parents=True, exist_ok=True)
    job_child_path(directory, "vdj", "input.fasta").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _load_profile(animal: str) -> tuple[dict[str, Any] | None, str]:
    path = PROFILE_ROOT / animal.lower() / "profile.json"
    if path.is_symlink() or not path.is_file():
        return None, "Профиль IMGT для животного не установлен."
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "Профиль IMGT повреждён или недоступен."
    if not isinstance(profile, dict):
        return None, "Профиль IMGT имеет недопустимый формат."
    required = ("id", "version", "v_db", "j_db", "auxiliary_data", "igdata")
    if not all(isinstance(profile.get(key), str) and profile[key] for key in required):
        return None, "Профиль IMGT не содержит обязательные параметры IgBLAST."
    organism = profile.get("organism")
    custom_internal_data = profile.get("custom_internal_data")
    if not (isinstance(organism, str) and organism) and not (
        isinstance(custom_internal_data, str) and custom_internal_data
    ):
        return None, "Профиль IMGT не задаёт системную или собственную разметку IgBLAST."
    chain_groups = profile.get("chain_groups")
    if chain_groups is not None and (
        not isinstance(chain_groups, list)
        or not chain_groups
        or not all(item in {"VHeavy", "VHH", "VKappa", "VLambda"} for item in chain_groups)
    ):
        return None, "Профиль IMGT содержит недопустимый список типов цепей."
    path_keys = ["v_db", "j_db", "auxiliary_data", "igdata"]
    if isinstance(profile.get("d_db"), str) and profile["d_db"]:
        path_keys.append("d_db")
    if isinstance(custom_internal_data, str) and custom_internal_data:
        path_keys.append("custom_internal_data")
    if not all(_profile_path_safe(profile[key]) for key in path_keys):
        return None, "Профиль IMGT содержит небезопасный путь к базе."
    return profile, ""


def _profile_path_safe(value: str) -> bool:
    try:
        return Path(value).resolve(strict=False).is_relative_to(IGBLAST_ROOT)
    except (OSError, ValueError):
        return False


def _run_profile(
    directory: Path,
    animal: str,
    entries: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    root = job_child_path(directory, "vdj", animal)
    root.mkdir(parents=True, exist_ok=True)
    query = root / "input.fasta"
    query.write_text("".join(f">{item['id']}\n{_normalise_dna(str(item['nucleotide_sequence']))}\n" for item in entries), encoding="utf-8")
    output = root / "rearrangements.tsv"
    detailed_output = root / "igblast_report.txt"
    common = ["igblastn", "-query", str(query)]
    custom_internal_data = profile.get("custom_internal_data")
    if isinstance(custom_internal_data, str) and custom_internal_data:
        common.extend(("-custom_internal_data", custom_internal_data))
    else:
        common.extend(("-organism", str(profile["organism"])))
    common.extend(("-germline_db_V", str(profile["v_db"])))
    if isinstance(profile.get("d_db"), str) and profile["d_db"]:
        common.extend(("-germline_db_D", str(profile["d_db"])))
    common.extend(("-germline_db_J", str(profile["j_db"]), "-auxiliary_data", str(profile["auxiliary_data"]), "-domain_system", "imgt", "-num_threads", "1"))
    airr_command = [*common, "-outfmt", "19", "-out", str(output)]
    detailed_command = [*common, "-show_translation", "-outfmt", "3", "-out", str(detailed_output)]
    # IgBLAST всё равно открывает встроенную базу аннотаций организма (по
    # умолчанию human_V) до применения -custom_internal_data. Поэтому для
    # собственных аннотаций оставляем IGDATA на полном дереве поставки IgBLAST,
    # а профильный .ndm.imgt передаём отдельным абсолютным путём.
    igdata = IGBLAST_ROOT if isinstance(custom_internal_data, str) and custom_internal_data else profile["igdata"]
    environment = {**os.environ, "IGDATA": str(igdata)}
    airr_completed = subprocess.run(airr_command, cwd=root, env=environment, check=False, capture_output=True, text=True)
    commands = [_command_metadata(animal, profile, "airr", airr_command, airr_completed)]
    _log_command(directory, commands[-1])
    if airr_completed.returncode != 0:
        return {}, {}, commands
    detailed_completed = subprocess.run(detailed_command, cwd=root, env=environment, check=False, capture_output=True, text=True)
    commands.append(_command_metadata(animal, profile, "detailed", detailed_command, detailed_completed))
    _log_command(directory, commands[-1])
    rows = _read_airr(output)
    _append_tsv(directory, output, animal)
    if detailed_completed.returncode != 0:
        return rows, {}, commands
    try:
        detailed_reports = _read_detailed_reports(detailed_output)
    except ValueError as error:
        commands[-1]["parse_error"] = str(error)
        _log(directory, str(error))
        detailed_reports = {}
    return rows, detailed_reports, commands


def _command_metadata(
    animal: str,
    profile: Mapping[str, Any],
    output_format: str,
    command: Sequence[str],
    completed: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    return {"animal": animal, "profile_id": profile["id"], "output_format": output_format, "argv": list(command), "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _log_command(directory: Path, command: Mapping[str, Any]) -> None:
    label = "AIRR" if command["output_format"] == "airr" else "подробный отчёт"
    _log(directory, f"IgBLAST {command['animal']} ({label}): код {command['returncode']}.")
    if command.get("stdout"):
        _log(directory, f"IgBLAST {command['animal']} stdout:\n{command['stdout']}")
    if command.get("stderr"):
        _log(directory, f"IgBLAST {command['animal']} stderr:\n{command['stderr']}")


def _read_airr(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("IgBLAST не создал rearrangements.tsv.")
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
    except (OSError, csv.Error) as error:
        raise ValueError("Не удалось прочитать AIRR-результат IgBLAST.") from error
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        identifier = row.get("sequence_id") or row.get("sequence") or row.get("sequence_header")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError("AIRR-результат содержит недопустимый или повторяющийся sequence_id.")
        result[identifier] = {key: value for key, value in row.items() if isinstance(key, str) and isinstance(value, str)}
    return result


_QUERY_REPORT = re.compile(r"(?m)^Query=\s+(\S+)\s*$")


def _read_detailed_reports(path: Path) -> dict[str, dict[str, Any]]:
    """Разделяет стандартный отчёт IgBLAST и сохраняет четыре блока viewer."""

    if not path.is_file() or path.is_symlink():
        raise ValueError("IgBLAST не создал подробный текстовый отчёт.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("Не удалось прочитать подробный отчёт IgBLAST.") from error
    matches = list(_QUERY_REPORT.finditer(text))
    if not matches:
        raise ValueError("Подробный отчёт IgBLAST не содержит блоков Query.")
    reports: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        sequence_id = match.group(1)
        if sequence_id in reports:
            raise ValueError("Подробный отчёт IgBLAST содержит повторяющийся Query ID.")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start():end].strip()
        reports[sequence_id] = _detailed_sections(block)
    return reports


def _detailed_sections(block: str) -> dict[str, Any]:
    length_match = re.search(r"(?m)^Length=(\d+)\s*$", block)
    return {
        "query_length": int(length_match.group(1)) if length_match else None,
        "significant_alignments": _report_section(block, "Sequences producing significant alignments:", ("Domain classification requested:", "V-(D)-J rearrangement summary")),
        "alignments": _report_section(block, "Alignments", ("Lambda      K", "Effective search space used:")),
    }


def _report_section(block: str, marker: str, end_markers: Sequence[str]) -> str | None:
    start = block.find(marker)
    if start < 0:
        return None
    end = len(block)
    for end_marker in end_markers:
        position = block.find(end_marker, start + len(marker))
        if position >= 0:
            end = min(end, position)
    value = block[start + len(marker):end].strip()
    return value or None


def _append_tsv(directory: Path, source: Path, animal: str) -> None:
    target = job_child_path(directory, "vdj", "rearrangements.tsv")
    if not source.is_file():
        return
    text = source.read_text(encoding="utf-8")
    if not target.exists() or target.stat().st_size == 0:
        target.write_text(text, encoding="utf-8")
        return
    lines = text.splitlines()
    if len(lines) > 1:
        with target.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines[1:]) + "\n")


def _result_from_airr(sequence_id: str, row: Mapping[str, str], details: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    query_length = details.get("query_length")
    alignment_length = _coordinate_span(row.get("v_sequence_start"), row.get("v_sequence_end"))
    coverage = round(alignment_length * 100 / query_length, 3) if alignment_length is not None and isinstance(query_length, int) and query_length > 0 else None
    return {"sequence_id": sequence_id, "status": "ready", "reason": None, "profile_id": profile["id"], "profile_version": profile["version"], "tool_version": None, "v_calls": _calls(row.get("v_call")), "d_calls": _calls(row.get("d_call")), "j_calls": _calls(row.get("j_call")), "locus": _none(row.get("locus")), "junction": {"nt": _none(row.get("junction")), "aa": _none(row.get("junction_aa"))}, "metrics": {"identity": _number(row.get("v_identity") or row.get("v_identity_aa")), "alignment_length": alignment_length, "coverage": coverage, "score": _number(row.get("v_score")), "evalue": _number(row.get("v_support"))}, "details": dict(details)}


def _unavailable(sequence_id: str, reason: str, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _empty_result(sequence_id, "unavailable", reason, profile)


def _failed(sequence_id: str, reason: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    return _empty_result(sequence_id, "failed", reason, profile)


def _ambiguous(sequence_id: str, reason: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    return _empty_result(sequence_id, "ambiguous", reason, profile)


def _empty_result(sequence_id: str, status: str, reason: str, profile: Mapping[str, Any] | None) -> dict[str, Any]:
    return {"sequence_id": sequence_id, "status": status, "reason": reason, "profile_id": profile.get("id") if profile else None, "profile_version": profile.get("version") if profile else None, "tool_version": None, "v_calls": [], "d_calls": [], "j_calls": [], "locus": None, "junction": {"nt": None, "aa": None}, "metrics": {"identity": None, "alignment_length": None, "coverage": None, "score": None, "evalue": None}, "details": {"query_length": None, "significant_alignments": None, "alignments": None}}


def _coordinate_span(start: str | None, end: str | None) -> int | None:
    start_value = _number(start)
    end_value = _number(end)
    if not isinstance(start_value, int) or not isinstance(end_value, int) or end_value < start_value:
        return None
    return end_value - start_value + 1


def _write_result(directory: Path, parent_job_id: str | None, records: Sequence[Mapping[str, Any]], commands: Sequence[Mapping[str, Any]]) -> None:
    profiles = sorted({(item.get("profile_id"), item.get("profile_version")) for item in records if item.get("profile_id")})
    profile_rows = [{"id": profile_id, "version": version, "source": "IMGT"} for profile_id, version in profiles]
    _write_json(job_child_path(directory, "vdj", "result.json"), {"version": 2, "parent_job_id": parent_job_id, "source": "IMGT", "profile": profile_rows[0] if len(profile_rows) == 1 else None, "profiles": profile_rows, "records": list(records), "commands": list(commands)})
    _write_json(job_child_path(directory, "vdj", "manifest.json"), {"version": 1, "parent_job_id": parent_job_id, "profiles_root": str(PROFILE_ROOT), "source": "IMGT", "profiles": profile_rows, "sequence_ids": [item["sequence_id"] for item in records]})


def _order_results(records: Sequence[Mapping[str, Any]], sequence_ids: Sequence[str]) -> list[dict[str, Any]]:
    by_id = {str(item["sequence_id"]): dict(item) for item in records}
    if len(by_id) != len(records) or set(by_id) != set(sequence_ids):
        raise ValueError("V(D)J-анализ сформировал неполный или повторяющийся набор результатов.")
    return [by_id[item] for item in sequence_ids]


def _valid_dna(value: str) -> bool:
    return bool(value) and all(base in "ACGTNacgtn" for base in "".join(value.split()))


def _normalise_dna(value: str) -> str:
    cleaned = "".join(value.split()).upper()
    if not _valid_dna(cleaned):
        raise ValueError("nucleotide_sequence содержит недопустимые символы.")
    return cleaned


def _calls(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _none(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: str | None) -> float | int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Артефакт {label} недоступен или повреждён.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Артефакт {label} имеет недопустимый формат.")
    return value


def _log(directory: Path, message: str) -> None:
    with job_child_path(directory, "log.txt").open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")
