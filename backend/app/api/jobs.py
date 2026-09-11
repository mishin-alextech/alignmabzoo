"""HTTP-маршруты создания job, просмотра состояния и загрузки артефактов."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, model_validator

from app.services.discovery import DiscoveryService, get_discovery_service
from app.services.job_pipeline import SelectionError, schedule_job, validate_selection
from app.services.realignment import alignment_records, schedule_realignment
from app.services.clustering import CLUSTER_COVERAGES, CLUSTER_IDENTITIES, schedule_clustering
from app.services.job_registry import JobNotFoundError, JobRecord, JobRegistry, JobRegistryError, get_job_registry


class JobCreateRequest(BaseModel):
    """Запрос создания job с пользовательским названием и выбором данных."""

    name: str
    selection: Any


class JobDeleteRequest(BaseModel):
    """Запрос пакетного удаления завершённых job."""

    job_ids: list[str] = Field(min_length=1)


class RealignRequest(BaseModel):
    """Запрос повторного выравнивания по стабильным ID последовательностей."""

    sequence_ids: list[str] = Field(min_length=1)


class ClusterRequest(BaseModel):
    """Параметры запуска MMseqs2 только по сохранённым ID родительской job."""

    sequence_ids: list[str] = Field(min_length=1)
    scope: Literal["cdr3", "variable_domain"]
    numbering_scheme: Literal["imgt", "kabat", "chothia"] | None = None
    min_seq_id: float = 0.90
    coverage: float = 0.90

    @model_validator(mode="after")
    def validate_parameters(self) -> "ClusterRequest":
        if self.scope == "cdr3" and self.numbering_scheme is None:
            raise ValueError("Для кластеризации CDR3 выберите схему нумерации.")
        if self.scope == "variable_domain" and self.numbering_scheme is not None:
            raise ValueError("Схема нумерации нужна только для кластеризации CDR3.")
        if self.min_seq_id not in CLUSTER_IDENTITIES or self.coverage not in CLUSTER_COVERAGES:
            raise ValueError("Допустимые инженерные пороги: идентичность 0.80, 0.90 или 0.95; покрытие 0.80 или 0.90.")
        return self


RegistryDependency = Annotated[JobRegistry, Depends(get_job_registry)]
DiscoveryDependency = Annotated[DiscoveryService, Depends(get_discovery_service)]
JobId = Annotated[str, ApiPath(description="UUID job")]

router = APIRouter(prefix="/jobs", tags=["Задачи обработки"])


def _registry_error(error: JobRegistryError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(error, JobNotFoundError) else 400, detail=str(error))


@router.post("", response_model=JobRecord, status_code=201)
async def create_job(request: JobCreateRequest, registry: RegistryDependency, discovery: DiscoveryDependency) -> JobRecord:
    """Создаёт queued-job после проверки выбранных каталогов и планирует её выполнение."""

    try:
        if not isinstance(request.selection, dict):
            raise SelectionError("Выбор job должен быть JSON-объектом.")
        await asyncio.to_thread(validate_selection, request.selection, discovery)
        job = await asyncio.to_thread(registry.create, request.name, request.selection)
    except SelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except JobRegistryError as error:
        raise _registry_error(error) from error
    schedule_job(job, registry, discovery)
    return job


@router.get("", response_model=list[JobRecord])
def list_jobs(registry: RegistryDependency) -> tuple[JobRecord, ...]:
    """Возвращает сохранённый список job."""

    try:
        return registry.list()
    except JobRegistryError as error:
        raise _registry_error(error) from error


@router.delete("")
def delete_jobs(request: JobDeleteRequest, registry: RegistryDependency) -> dict[str, list[str]]:
    """Удаляет только завершённые job и принадлежащие им каталоги результатов."""

    try:
        deleted_ids = registry.delete_terminal(request.job_ids)
    except JobRegistryError as error:
        raise _registry_error(error) from error
    return {"deleted_ids": list(deleted_ids)}


@router.get("/{job_id}", response_model=JobRecord)
def get_job(job_id: JobId, registry: RegistryDependency) -> JobRecord:
    """Возвращает состояние одной job."""

    try:
        return registry.get(job_id)
    except JobRegistryError as error:
        raise _registry_error(error) from error


@router.post("/{job_id}/realign", response_model=JobRecord, status_code=201)
async def realign_job(
    job_id: JobId,
    request: RealignRequest,
    registry: RegistryDependency,
) -> JobRecord:
    """Создаёт производную job по сохранённым белкам родительской job."""

    job = await asyncio.to_thread(_create_realignment, job_id, request, registry)
    schedule_realignment(job.id, registry)
    return job


def _create_realignment(job_id: str, request: RealignRequest, registry: JobRegistry) -> JobRecord:
    """Читает артефакты вне event loop и проверяет также ID старых результатов."""

    try:
        parent = registry.get(job_id)
        alignment = json.loads(_text_artifact(registry, job_id, "alignment.json"))
        if not isinstance(alignment, dict):
            raise ValueError("Артефакт выравнивания должен быть JSON-объектом.")
        available_ids = set(alignment_records(alignment))
        selected_ids = tuple(dict.fromkeys(request.sequence_ids))
        if not set(selected_ids).issubset(available_ids):
            raise JobRegistryError("Один или несколько sequence_id отсутствуют в родительском выравнивании.")
        job = registry.create_derived(parent.id, selected_ids)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Артефакт alignment.json содержит некорректный JSON.") from error
    except JobRegistryError as error:
        raise _registry_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return job


@router.post("/{job_id}/cluster", response_model=JobRecord, status_code=201)
async def cluster_job(job_id: JobId, request: ClusterRequest, registry: RegistryDependency) -> JobRecord:
    """Создаёт независимую job MMseqs2 по стабильным ID готового MSA."""

    job = await asyncio.to_thread(_create_clustering, job_id, request, registry)
    schedule_clustering(job.id, registry)
    return job


def _create_clustering(job_id: str, request: ClusterRequest, registry: JobRegistry) -> JobRecord:
    """Проверяет принадлежность ID готовому MSA до создания фоновой job."""

    try:
        parent = registry.get(job_id)
        alignment = json.loads(_text_artifact(registry, job_id, "alignment.json"))
        if not isinstance(alignment, dict):
            raise ValueError("Артефакт выравнивания должен быть JSON-объектом.")
        available_ids = set(alignment_records(alignment))
        selected_ids = tuple(dict.fromkeys(request.sequence_ids))
        if not all(sequence_id.startswith("seq_") for sequence_id in selected_ids):
            raise JobRegistryError("Кластеризация доступна только для стабильных ID современных результатов.")
        if not set(selected_ids).issubset(available_ids):
            raise JobRegistryError("Один или несколько sequence_id отсутствуют в родительском выравнивании.")
        job = registry.create_clustering(
            parent.id,
            selected_ids,
            scope=request.scope,
            numbering_scheme=request.numbering_scheme,
            min_seq_id=request.min_seq_id,
            coverage=request.coverage,
        )
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Артефакт alignment.json содержит некорректный JSON.") from error
    except JobRegistryError as error:
        raise _registry_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return job


@router.get("/{job_id}/alignments")
def get_alignments(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает JSON для viewer множественного выравнивания."""

    return _json_artifact(registry, job_id, "alignment.json")


@router.get("/{job_id}/exclusions")
def get_exclusions(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает отчёт о пропущенных и ошибочных входных данных."""

    return _json_artifact(registry, job_id, "report.json")


@router.get("/{job_id}/clusters")
def get_clusters(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает нормализованные кластеры и порядок строк для viewer."""

    return _json_artifact(registry, job_id, "clustering/clusters.json")


@router.get("/{job_id}/log")
def get_log(job_id: JobId, registry: RegistryDependency) -> PlainTextResponse:
    """Возвращает текущий append-only лог job."""

    return PlainTextResponse(_text_artifact(registry, job_id, "log.txt"))


@router.get("/{job_id}/report")
def get_report(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает report.json job."""

    return _json_artifact(registry, job_id, "report.json")


@router.get("/{job_id}/anarci")
def list_anarci_csv(job_id: JobId, registry: RegistryDependency) -> dict[str, list[str]]:
    """Возвращает только готовые CSV раздельных блоков ANARCI."""

    allowed = {
        f"{scheme}_{batch}.csv"
        for scheme in ("imgt", "kabat", "chothia")
        for batch in ("vheavy", "vkappa", "vlambda", "other")
    }
    directory = _directory(registry, job_id).resolve()
    anarci_directory = (directory / "anarci").resolve()
    if not anarci_directory.is_relative_to(directory) or not anarci_directory.is_dir():
        return {"files": []}
    files = sorted(
        path.name
        for path in anarci_directory.iterdir()
        if path.name in allowed and path.is_file() and not path.is_symlink()
    )
    return {"files": files}


@router.get("/{job_id}/alignments/{filename}")
def download_alignment(
    job_id: JobId, filename: str, registry: RegistryDependency
) -> FileResponse:
    """Скачивает одно из выравниваний Clustal по типу цепи."""

    allowed = {"vheavy.aln", "vkappa.aln", "vlambda.aln", "other.aln"}
    if filename not in allowed:
        raise HTTPException(status_code=400, detail="Указано недопустимое имя файла выравнивания.")
    return _file_artifact(registry, job_id, f"alignment/{filename}", filename)


@router.get("/{job_id}/anarci/{filename}")
def download_anarci_csv(job_id: JobId, filename: str, registry: RegistryDependency) -> FileResponse:
    """Скачивает один нативный CSV ANARCI из каталога job."""

    if not filename.endswith(".csv") or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Указано недопустимое имя CSV-файла.")
    return _file_artifact(registry, job_id, f"anarci/{filename}", filename)


def _directory(registry: JobRegistry, job_id: str) -> Path:
    try:
        return registry.directory_for(job_id)
    except JobRegistryError as error:
        raise _registry_error(error) from error


def _artifact(registry: JobRegistry, job_id: str, name: str) -> Path:
    directory = _directory(registry, job_id).resolve()
    candidate = (directory / name).resolve()
    if not candidate.is_relative_to(directory) or candidate.is_symlink() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Артефакт job пока недоступен.")
    return candidate


def _text_artifact(registry: JobRegistry, job_id: str, name: str) -> str:
    artifact = _artifact(registry, job_id, name)
    try:
        return artifact.read_text(encoding="utf-8")
    except OSError as error:
        raise HTTPException(status_code=500, detail="Не удалось прочитать артефакт job.") from error


def _json_artifact(registry: JobRegistry, job_id: str, name: str) -> JSONResponse:
    try:
        return JSONResponse(json.loads(_text_artifact(registry, job_id, name)))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Артефакт job содержит некорректный JSON.") from error


def _file_artifact(registry: JobRegistry, job_id: str, name: str, download_name: str) -> FileResponse:
    return FileResponse(_artifact(registry, job_id, name), filename=download_name, media_type="application/octet-stream")
