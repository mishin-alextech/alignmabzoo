"""Конфигурация приложения без побочных действий при импорте."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Пути контейнера и базовые настройки сервиса."""

    model_config = SettingsConfigDict(env_prefix="ALIGNMABZOO_", extra="ignore")

    data_root: Path = Path("/synced_data/mabzoo")
    jobs_root: Path = Path("/app/jobs")
    static_root: Path = Path("/app/app/static")


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированную конфигурацию из переменных окружения."""

    return Settings()

