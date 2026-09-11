"""Кластеризация сохранённых последовательностей MMseqs2 без доступа к data-root."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from app.services.alignment import msa_identifier
from app.services.anarci_runner import job_child_path, validate_job_directory
from app.services.job_pipeline import _job_semaphore
from app.services.job_registry import JobRegistry, JobStatus, retain_job_task
from app.services.realignment import alignment_records


ClusterScope = Literal["cdr3", "variable_domain"]
CLUSTER_IDENTITIES = frozenset({0.80, 0.90, 0.95})
CLUSTER_COVERAGES = frozenset({0.80, 0.90})


async def run_clustering(job_id: str, registry: JobRegistry) -> None:
    """Запускает кластеризацию под тем же лимитом, что и MSA."""

    async with _job_semaphore:
        await asyncio.to_thread(_run_clustering_sync, job_id, registry)


def schedule_clustering(job_id: str, registry: JobRegistry) -> asyncio.Task[None]:
    """Удерживает фоновую задачу до её завершения."""

    return retain_job_task(asyncio.create_task(run_clustering(job_id, registry), name=f"alignmabzoo-clustering-{job_id}"))


def _run_clustering_sync(job_id: str, registry: JobRegistry) -> None:
    report: dict[str, Any] = {"processed": [], "skipped": [], "errors": [], "unclustered": []}
    counts = {"files_found": 0, "files_processed": 0, "files_skipped": 0, "files_failed": 0, "sequences": 0}
    record = None
    directory: Path | None = None
    try:
        record = registry.get(job_id)
        directory = validate_job_directory(registry.directory_for(job_id), registry.jobs_root)
        registry.update_status(job_id, JobStatus.RUNNING)
        parameters = _parameters(record.selection.root)
        if not record.parent_job_id:
            raise ValueError("У job кластеризации отсутствует родительская job.")
        parent_directory = validate_job_directory(registry.directory_for(record.parent_job_id), registry.jobs_root)
        parent_alignment = _read_json(parent_directory / "alignment.json", "alignment.json")
        records = alignment_records(parent_alignment)
        selected_ids = tuple(record.sequence_ids)
        if not selected_ids or not set(selected_ids).issubset(records):
            raise ValueError("Выбранные ID отсутствуют в сохранённом выравнивании.")
        counts["files_found"] = len(selected_ids)
        candidates, unclustered = _cluster_inputs(records, selected_ids, parameters)
        report["unclustered"].extend(unclustered)
        report["skipped"].extend(unclustered)
        _write_sequence_map(directory, candidates, unclustered)
        tool = _tool_metadata()
        clusters, commands = _cluster_by_group(candidates, directory, parameters)
        _write_log(directory, "Кластеризация запущена.")
        for command in commands:
            _write_log(directory, f"Команда: {' '.join(command['argv'])}; код возврата: {command['returncode']}.")
            if command["stdout"]:
                _write_log(directory, f"Вывод команды (stdout):\n{command['stdout']}")
            if command["stderr"]:
                _write_log(directory, f"Вывод команды (stderr):\n{command['stderr']}")
        ordered = _normalise_clusters(clusters, candidates)
        _write_json(directory / "clustering" / "clusters.json", {"clusters": ordered, "unclustered": unclustered, "order": _viewer_order(ordered, unclustered)})
        manifest = {
            "version": 1,
            "parent_job_id": record.parent_job_id,
            "sequence_ids": list(selected_ids),
            "scope": parameters["scope"],
            "numbering_scheme": parameters.get("numbering_scheme"),
            "parameters": {"min_seq_id": parameters["min_seq_id"], "coverage": parameters["coverage"], "alignment_mode": 3, "seq_id_mode": 0, "cov_mode": 0, "cluster_mode": 0, "cluster_reassign": 1, "threads": 1},
            "tool": tool,
            "commands": commands,
            "input_sha256": _input_hash(candidates),
        }
        _write_json(directory / "clustering" / "manifest.json", manifest)
        report["processed"] = [{"id": item["id"], "path": item["name"]} for item in candidates]
        counts["files_processed"] = counts["sequences"] = len(candidates)
        counts["files_skipped"] = len(unclustered)
        counts["files_failed"] = 0
        _write_json(directory / "report.json", report)
        status = JobStatus.PARTIAL if unclustered else JobStatus.DONE
        _write_log(directory, f"Кластеризация завершена: {status.value}; пригодных последовательностей: {len(candidates)}.")
        registry.update_status(job_id, status, counts=counts)
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) else f"Не удалось выполнить кластеризацию: {error}"
        report["errors"].append({"path": "job", "reason": reason})
        if directory is not None:
            try:
                _write_log(directory, reason)
                _write_json(directory / "report.json", report)
            except OSError:
                pass
        if record is not None:
            registry.update_status(job_id, JobStatus.FAILED, counts=counts, failure_reason=reason)


def _parameters(selection: Mapping[str, Any]) -> dict[str, Any]:
    scope = selection.get("scope")
    scheme = selection.get("numbering_scheme")
    min_seq_id = selection.get("min_seq_id")
    coverage = selection.get("coverage")
    if scope not in ("cdr3", "variable_domain"):
        raise ValueError("Область кластеризации должна быть CDR3 или вариабельным доменом.")
    if scope == "cdr3" and scheme not in ("imgt", "kabat", "chothia"):
        raise ValueError("Для кластеризации CDR3 требуется схема нумерации IMGT, Kabat или Chothia.")
    if scope == "variable_domain" and scheme is not None:
        raise ValueError("Схема нумерации задаётся только для кластеризации CDR3.")
    if min_seq_id not in CLUSTER_IDENTITIES or coverage not in CLUSTER_COVERAGES:
        raise ValueError("Указаны недопустимые инженерные пороги кластеризации.")
    return {"scope": scope, "numbering_scheme": scheme, "min_seq_id": min_seq_id, "coverage": coverage}


def _cluster_inputs(records: Mapping[str, Mapping[str, Any]], selected_ids: Sequence[str], parameters: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    candidates: list[dict[str, str]] = []
    unclustered: list[dict[str, str]] = []
    for sequence_id in selected_ids:
        record = records[sequence_id]
        sequence = record.get("seq")
        if not isinstance(sequence, str):
            unclustered.append({"id": sequence_id, "reason": "В сохранённом выравнивании отсутствует белковая последовательность."})
            continue
        protein = _ungap(sequence)
        if parameters["scope"] == "cdr3":
            cdr = ((record.get("cdr") or {}).get(parameters["numbering_scheme"], {}) or {}).get("cdr3")
            if not isinstance(cdr, list):
                unclustered.append({"id": sequence_id, "reason": "Для последовательности отсутствует CDR3 выбранной схемы."})
                continue
            residues = [sequence[index] for index in cdr if isinstance(index, int) and 0 <= index < len(sequence) and sequence[index] not in "-."]
            protein = "".join(residues).upper()
            if not protein:
                unclustered.append({"id": sequence_id, "reason": "CDR3 выбранной схемы не содержит аминокислот."})
                continue
        if not protein or not protein.isascii() or not protein.isalpha():
            unclustered.append({"id": sequence_id, "reason": "Последовательность не пригодна для MMseqs2."})
            continue
        candidates.append({"id": sequence_id, "msa_id": msa_identifier(sequence_id), "name": str(record.get("name", sequence_id)), "group": str(record.get("group", "Other")), "sequence": protein})
    return candidates, unclustered


def _cluster_by_group(candidates: Sequence[Mapping[str, str]], directory: Path, parameters: Mapping[str, Any]) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for item in candidates:
        grouped[item["group"]].append(item)
    clusters: dict[str, list[str]] = {}
    commands: list[dict[str, Any]] = []
    for group, items in grouped.items():
        group_directory = directory / "clustering" / _safe_group_name(group)
        group_directory.mkdir(parents=True, exist_ok=True)
        input_path = group_directory / "input.fasta"
        input_path.write_text("".join(f">{item['msa_id']}\n{item['sequence']}\n" for item in items), encoding="utf-8")
        if len(items) == 1:
            clusters[items[0]["id"]] = [items[0]["id"]]
            continue
        output_prefix = group_directory / "result"
        tmp_directory = group_directory / "tmp"
        argv = ["mmseqs", "easy-cluster", str(input_path), str(output_prefix), str(tmp_directory), "--min-seq-id", str(parameters["min_seq_id"]), "-c", str(parameters["coverage"]), "--alignment-mode", "3", "--seq-id-mode", "0", "--cov-mode", "0", "--cluster-mode", "0", "--cluster-reassign", "1", "--threads", "1"]
        result = subprocess.run(argv, cwd=group_directory, check=False, capture_output=True, text=True)
        command = {"group": group, "argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        commands.append(command)
        if result.returncode != 0:
            detail = " ".join(result.stderr.split())[:500]
            raise ValueError("MMseqs2 завершился с ошибкой" + (f": {detail}" if detail else ""))
        source_tsv = Path(f"{output_prefix}_cluster.tsv")
        result_tsv = group_directory / "result_cluster.tsv"
        if not source_tsv.is_file():
            raise ValueError("MMseqs2 не создал таблицу кластеров.")
        if source_tsv != result_tsv:
            shutil.copyfile(source_tsv, result_tsv)
        tool_to_stable = {item["msa_id"]: item["id"] for item in items}
        for representative, member in _read_tsv(result_tsv, tool_to_stable).items():
            if representative in clusters:
                raise ValueError("MMseqs2 повторно назначил представителя кластера.")
            clusters[representative] = member
    return clusters, commands


def _read_tsv(path: Path, known: Mapping[str, str]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = defaultdict(list)
    seen_members: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] not in known or parts[1] not in known:
            raise ValueError("Таблица MMseqs2 содержит неизвестный или недопустимый ID.")
        representative, member = known[parts[0]], known[parts[1]]
        if member in seen_members:
            raise ValueError("Таблица MMseqs2 повторно назначает участника кластеру.")
        seen_members.add(member)
        rows[representative].append(member)
    if seen_members != set(known.values()):
        raise ValueError("Таблица MMseqs2 не содержит все входные последовательности.")
    return dict(rows)


def _normalise_clusters(clusters: Mapping[str, Sequence[str]], candidates: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in candidates}
    result: list[dict[str, Any]] = []
    for representative, members in clusters.items():
        if representative not in members:
            raise ValueError("Таблица MMseqs2 не содержит self-hit представителя.")
        ordered_members = [representative] + sorted((item for item in members if item != representative), key=lambda item: (by_id[item]["name"], item))
        cluster_id = "cluster_" + hashlib.sha256((representative + "\0" + "\0".join(sorted(members))).encode("utf-8")).hexdigest()[:20]
        result.append({"id": cluster_id, "representative_id": representative, "sequence_ids": ordered_members, "chain_group": by_id[representative]["group"], "size": len(ordered_members)})
    return sorted(result, key=lambda item: (item["chain_group"], -item["size"], item["representative_id"]))


def _viewer_order(clusters: Sequence[Mapping[str, Any]], unclustered: Sequence[Mapping[str, str]]) -> list[str]:
    order = [sequence_id for cluster in clusters for sequence_id in cluster["sequence_ids"]]
    return order + [item["id"] for item in unclustered]


def _write_sequence_map(directory: Path, candidates: Sequence[Mapping[str, str]], unclustered: Sequence[Mapping[str, str]]) -> None:
    rows = [{key: item[key] for key in ("id", "msa_id", "name", "group")} for item in candidates]
    _write_json(directory / "clustering" / "sequence_map.json", {"sequences": rows, "unclustered": list(unclustered)})


def _tool_metadata() -> dict[str, str | None]:
    version = None
    try:
        version_result = subprocess.run(["mmseqs", "version"], check=False, capture_output=True, text=True)
        if version_result.returncode == 0:
            version = version_result.stdout.strip() or version_result.stderr.strip() or None
    except OSError:
        pass
    revision_path = Path("/usr/local/share/mmseqs2-revision")
    try:
        revision = revision_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        revision = None
    return {"version": version, "git_sha": revision}


def _input_hash(candidates: Sequence[Mapping[str, str]]) -> str:
    content = "".join(f"{item['id']}\0{item['sequence']}\n" for item in sorted(candidates, key=lambda item: item["id"]))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Артефакт {label} недоступен или повреждён.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Артефакт {label} имеет недопустимый формат.")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_log(directory: Path, message: str) -> None:
    with job_child_path(directory, "log.txt").open("a", encoding="utf-8") as output:
        output.write(message + "\n")


def _safe_group_name(group: str) -> str:
    return {"VHeavy": "vheavy", "VHH": "vhh", "VKappa": "vkappa", "VLambda": "vlambda", "Other": "other"}.get(group, "other")


def _ungap(sequence: str) -> str:
    return sequence.replace("-", "").replace(".", "").upper()
