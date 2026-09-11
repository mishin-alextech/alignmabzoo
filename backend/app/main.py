"""ASGI-приложение AlignMabZoo."""

import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.browse import router as browse_router
from app.api.jobs import router as jobs_router
from app.config import get_settings
from app.services.job_registry import JobKind, JobStatus, get_job_registry
from app.services.job_pipeline import schedule_job
from app.services.realignment import schedule_realignment
from app.services.clustering import schedule_clustering


settings = get_settings()

app = FastAPI(
    title="AlignMabZoo",
    description="Сервис обработки последовательностей моноклональных антител.",
    version="0.1.0",
)
app.include_router(health_router, prefix="/api")
app.include_router(browse_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.on_event("startup")
async def recover_interrupted_jobs() -> None:
    """Помечает job, прерванные перезапуском контейнера, как failed."""

    registry = get_job_registry()
    await asyncio.to_thread(registry.recover_interrupted_running)
    for job in await asyncio.to_thread(registry.list):
        if job.status is JobStatus.QUEUED:
            if job.kind is JobKind.CLUSTERING:
                schedule_clustering(job.id, registry)
            elif job.kind is JobKind.REALIGNMENT or job.parent_job_id:
                schedule_realignment(job.id, registry)
            else:
                schedule_job(job, registry)

# Собранный React-клиент будет помещён в этот каталог при сборке образа.
app.mount(
    "/",
    StaticFiles(directory=str(settings.static_root), html=True, check_dir=False),
    name="frontend",
)
