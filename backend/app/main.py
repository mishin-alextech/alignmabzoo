"""ASGI-приложение AlignMabZoo."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.browse import router as browse_router
from app.api.jobs import router as jobs_router
from app.config import get_settings
from app.services.job_registry import get_job_registry


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

    get_job_registry().recover_interrupted_running()

# Собранный React-клиент будет помещён в этот каталог при сборке образа.
app.mount(
    "/",
    StaticFiles(directory=str(settings.static_root), html=True, check_dir=False),
    name="frontend",
)
