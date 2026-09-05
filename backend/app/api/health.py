"""Маршрут проверки доступности сервиса."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Ответ о доступности HTTP-сервиса."""

    status: Literal["ok"] = Field(description="Технический статус сервиса.")
    message: str = Field(description="Сообщение для пользователя.")


router = APIRouter(tags=["Служебные маршруты"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка доступности сервиса",
)
async def get_health() -> HealthResponse:
    """Возвращает статус работающего HTTP-сервиса."""

    return HealthResponse(status="ok", message="Сервис работает.")

