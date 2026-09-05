"""Безопасный read-only обзор структуры каталога исходных данных."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final

from app.config import get_settings


ANIMAL_DIRECTORIES: Final[dict[str, str]] = {
    "Ms": "1-2_Mouse mAbs_seq results",
    "Rb": "3_Rabbit mAbs_seq results",
    "Rt": "4-5_Rat mAbs_seq results",
    "Pg": "6_Pig_mAbs_seq_results",
    "Hu": "7_Human_mAbs_seq_results",
    "Hs": "80_83_Hamster_mAbs_seq_results",
    "Ov": "90_Ovis_Aries_mAbs_seq_results",
    "Gt": "92_Goat_mAbs_seq_results",
    "Cm": "94_95_Camelids_mAbs_seq_results",
    "Bv": "96_97_Bovine_mAbs_seq_results",
}


ANIMAL_NAMES: Final[dict[str, str]] = {
    "Ms": "Мышь",
    "Rb": "Кролик",
    "Rt": "Крыса",
    "Pg": "Свинья",
    "Hu": "Человек",
    "Hs": "Хомяк",
    "Ov": "Овца",
    "Gt": "Коза",
    "Cm": "Верблюд",
    "Bv": "Бык",
}


@dataclass(frozen=True, slots=True)
class Animal:
    """Описание поддерживаемого животного."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    """Значение кэша и mtime каталога, от которого оно зависит."""

    signature: tuple[int, int] | None
    value: tuple[str, ...]


class DiscoveryService:
    """Читает только имена директорий, не покидая корень исходных данных."""

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root
        self._resolved_root = data_root.resolve(strict=False)
        self._cache: dict[tuple[str, ...], _CacheEntry] = {}
        self._lock = RLock()

    @property
    def animals(self) -> tuple[Animal, ...]:
        """Возвращает фиксированный список поддерживаемых кодов животных."""

        return tuple(Animal(code=code, name=name) for code, name in ANIMAL_NAMES.items())

    def is_known_animal(self, animal_code: str) -> bool:
        """Проверяет, относится ли код к фиксированному справочнику."""

        return animal_code in ANIMAL_NAMES

    def animal_directory_name(self, animal_code: str) -> str:
        """Возвращает имя каталога животного в data-root для кода."""

        self._require_animal(animal_code)
        return ANIMAL_DIRECTORIES[animal_code]

    def list_projects(self, animal_code: str) -> tuple[str, ...]:
        """Возвращает проекты первого уровня для животного."""

        self._require_animal(animal_code)
        directory = self._child_directory(self._data_root, self.animal_directory_name(animal_code))
        return self._cached_directory_names(("projects", animal_code), directory)

    def has_project(self, animal_code: str, project: str) -> bool:
        """Проверяет существование проекта среди каталогов первого уровня."""

        return project in self.list_projects(animal_code)

    def list_groups(self, animal_code: str, project: str) -> tuple[str, ...]:
        """Возвращает группы первого уровня для проекта."""

        self._require_animal(animal_code)
        self._validate_component(project)
        animal_directory = self._child_directory(self._data_root, self.animal_directory_name(animal_code))
        project_directory = self._child_directory(animal_directory, project)
        return self._cached_directory_names(
            ("groups", animal_code, project), project_directory
        )

    def _require_animal(self, animal_code: str) -> None:
        if not self.is_known_animal(animal_code):
            raise ValueError(f"Код животного «{animal_code}» не поддерживается.")

    @staticmethod
    def _validate_component(component: str) -> None:
        """Запрещает абсолютные пути, разделители и специальные компоненты."""

        path = Path(component)
        if (
            not component
            or component in {".", ".."}
            or path.is_absolute()
            or len(path.parts) != 1
            or "/" in component
            or "\\" in component
        ):
            raise ValueError("Имя каталога содержит недопустимый путь.")

    def _child_directory(self, parent: Path, name: str) -> Path:
        """Возвращает безопасный дочерний путь без перехода по ссылкам."""

        self._validate_component(name)
        candidate = parent / name
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                return candidate
            resolved = candidate.resolve(strict=True)
        except OSError:
            return candidate
        if not resolved.is_relative_to(self._resolved_root):
            return candidate
        return candidate

    @staticmethod
    def _directory_signature(directory: Path) -> tuple[int, int] | None:
        """Получает mtime без чтения содержимого каталога."""

        try:
            if directory.is_symlink():
                return None
            stat = directory.stat(follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return (stat.st_mtime_ns, stat.st_ctime_ns)

    def _cached_directory_names(
        self, key: tuple[str, ...], directory: Path
    ) -> tuple[str, ...]:
        """Возвращает имена дочерних каталогов, обновляя кэш при смене mtime."""

        signature = self._directory_signature(directory)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.signature == signature:
                return cached.value
            value = self._read_directory_names(directory) if signature is not None else ()
            self._cache[key] = _CacheEntry(signature=signature, value=value)
            return value

    @staticmethod
    def _read_directory_names(directory: Path) -> tuple[str, ...]:
        """Сканирует только видимые реальные каталоги, не читая их файлов."""

        try:
            with os.scandir(directory) as entries:
                names = [
                    entry.name
                    for entry in entries
                    if not entry.name.startswith(".")
                    and not entry.is_symlink()
                    and entry.is_dir(follow_symlinks=False)
                ]
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            return ()
        return tuple(sorted(names, key=lambda value: (value.casefold(), value)))


_discovery_service: DiscoveryService | None = None
_service_lock = RLock()


def get_discovery_service() -> DiscoveryService:
    """Возвращает общий сервис обзора для настроенного data-root."""

    global _discovery_service
    settings = get_settings()
    with _service_lock:
        if _discovery_service is None or _discovery_service._data_root != settings.data_root:
            _discovery_service = DiscoveryService(settings.data_root)
        return _discovery_service
