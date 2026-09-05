"""HTTP-маршруты безопасного обзора каталога исходных данных."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.services.discovery import Animal, DiscoveryService, get_discovery_service


class AnimalItem(BaseModel):
    """Поддерживаемое животное в API-ответе."""

    code: str = Field(description="Двухбуквенный код каталога животного.")
    name: str = Field(description="Русскоязычное название животного.")


class AnimalsResponse(BaseModel):
    """Список поддерживаемых животных."""

    animals: list[AnimalItem]


class NameItem(BaseModel):
    """Имя проекта или группы."""

    name: str


class ProjectsResponse(BaseModel):
    """Список проектов животного."""

    animal_code: str
    projects: list[NameItem]


class GroupsResponse(BaseModel):
    """Список групп проекта."""

    animal_code: str
    project: str
    groups: list[NameItem]


ServiceDependency = Annotated[DiscoveryService, Depends(get_discovery_service)]
AnimalCode = Annotated[str, Path(min_length=2, max_length=2, description="Код животного")]
ProjectName = Annotated[str, Path(min_length=1, max_length=200, description="Имя проекта")]

router = APIRouter(tags=["Обзор исходных данных"])


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def _ensure_animal(service: DiscoveryService, animal_code: str) -> None:
    if not service.is_known_animal(animal_code):
        raise _not_found(f"Код животного «{animal_code}» не поддерживается.")


def _ensure_project(
    service: DiscoveryService, animal_code: str, project: str
) -> None:
    try:
        project_exists = service.has_project(animal_code, project)
    except ValueError as error:
        raise _not_found(str(error)) from error
    if not project_exists:
        raise _not_found(
            f"Проект «{project}» для животного «{animal_code}» не найден."
        )


@router.get("/animals", response_model=AnimalsResponse, summary="Список животных")
async def get_animals(service: ServiceDependency) -> AnimalsResponse:
    """Возвращает неизменный справочник животных, доступных для выбора."""

    return AnimalsResponse(
        animals=[AnimalItem(code=item.code, name=item.name) for item in service.animals]
    )


@router.get(
    "/animals/{animal_code}/projects",
    response_model=ProjectsResponse,
    summary="Список проектов животного",
)
async def get_projects(
    animal_code: AnimalCode, service: ServiceDependency
) -> ProjectsResponse:
    """Возвращает проекты первого уровня или пустой список при пустом data-root."""

    _ensure_animal(service, animal_code)
    return ProjectsResponse(
        animal_code=animal_code,
        projects=[NameItem(name=name) for name in service.list_projects(animal_code)],
    )


@router.get(
    "/animals/{animal_code}/projects/{project}/groups",
    response_model=GroupsResponse,
    summary="Список групп проекта",
)
async def get_groups(
    animal_code: AnimalCode, project: ProjectName, service: ServiceDependency
) -> GroupsResponse:
    """Возвращает группы первого уровня существующего проекта."""

    _ensure_animal(service, animal_code)
    _ensure_project(service, animal_code, project)
    try:
        groups = service.list_groups(animal_code, project)
    except ValueError as error:
        raise _not_found(str(error)) from error
    return GroupsResponse(
        animal_code=animal_code,
        project=project,
        groups=[NameItem(name=name) for name in groups],
    )


@router.get(
    "/projects/{animal_code}/{project}/groups",
    response_model=GroupsResponse,
    include_in_schema=False,
)
async def get_groups_compatibility(
    animal_code: AnimalCode, project: ProjectName, service: ServiceDependency
) -> GroupsResponse:
    """Поддерживает ранний вариант маршрута получения групп."""

    return await get_groups(animal_code, project, service)
