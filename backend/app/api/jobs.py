"""HTTP-маршруты создания job, просмотра состояния и загрузки артефактов."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.services.discovery import DiscoveryService, get_discovery_service
from app.services.job_pipeline import SelectionError, schedule_job, validate_selection
from app.services.job_registry import JobNotFoundError, JobRecord, JobRegistry, JobRegistryError, get_job_registry


class JobCreateRequest(BaseModel):
    """Запрос создания job с пользовательским названием и выбором данных."""

    name: str
    selection: Any


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
        validate_selection(request.selection, discovery)
        job = registry.create(request.name, request.selection)
    except SelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except JobRegistryError as error:
        raise _registry_error(error) from error
    schedule_job(job, registry, discovery)
    return job


@router.get("", response_model=list[JobRecord])
async def list_jobs(registry: RegistryDependency) -> tuple[JobRecord, ...]:
    """Возвращает сохранённый список job."""

    try:
        return registry.list()
    except JobRegistryError as error:
        raise _registry_error(error) from error


@router.get("/{job_id}", response_model=JobRecord)
async def get_job(job_id: JobId, registry: RegistryDependency) -> JobRecord:
    """Возвращает состояние одной job."""

    try:
        return registry.get(job_id)
    except JobRegistryError as error:
        raise _registry_error(error) from error


@router.get("/{job_id}/alignments")
async def get_alignments(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает JSON для viewer множественного выравнивания."""

    return _json_artifact(registry, job_id, "alignment.json")


@router.get("/{job_id}/exclusions")
async def get_exclusions(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает отчёт о пропущенных и ошибочных входных данных."""

    return _json_artifact(registry, job_id, "report.json")


@router.get("/{job_id}/log")
async def get_log(job_id: JobId, registry: RegistryDependency) -> PlainTextResponse:
    """Возвращает текущий append-only лог job."""

    return PlainTextResponse(_text_artifact(registry, job_id, "log.txt"))


@router.get("/{job_id}/report")
async def get_report(job_id: JobId, registry: RegistryDependency) -> JSONResponse:
    """Возвращает report.json job."""

    return _json_artifact(registry, job_id, "report.json")


@router.get("/{job_id}/alignment.aln")
async def download_alignment(job_id: JobId, registry: RegistryDependency) -> FileResponse:
    """Скачивает сформированное Clustal-выравнивание."""

    return _file_artifact(registry, job_id, "alignment/alignment.aln", "alignment.aln")


@router.get("/{job_id}/anarci/{filename}")
async def download_anarci_csv(job_id: JobId, filename: str, registry: RegistryDependency) -> FileResponse:
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
