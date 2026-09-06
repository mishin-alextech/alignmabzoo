"""Дисковый реестр job, изолированный в настроенном каталоге результатов."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Final, Mapping, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, ValidationError

from app.config import get_settings


REGISTRY_FILENAME: Final = "jobs_registry.json"
REGISTRY_VERSION: Final = 1
INTERRUPTED_REASON: Final = "Выполнение job было прервано перезапуском контейнера."


class JobRegistryError(RuntimeError):
    """Базовая ошибка безопасной работы с реестром job."""


class JobNotFoundError(JobRegistryError):
    """Запрошенная job отсутствует в реестре."""


class JobStatusTransitionError(JobRegistryError):
    """Запрошенный переход статуса не допускается."""


class JobStatus(StrEnum):
    """Допустимые состояния жизненного цикла job."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


TERMINAL_STATUSES: Final = frozenset(
    {JobStatus.DONE, JobStatus.PARTIAL, JobStatus.FAILED}
)
ALLOWED_TRANSITIONS: Final[dict[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    JobStatus.RUNNING: TERMINAL_STATUSES,
    JobStatus.DONE: frozenset(),
    JobStatus.PARTIAL: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class JobSelection(RootModel[dict[str, JsonValue]]):
    """JSON-сериализуемый выбор животных, проектов и групп пользователя."""

    model_config = ConfigDict(frozen=True)


class JobCounts(BaseModel):
    """Итоговые счётчики обработки job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    files_found: int = Field(default=0, ge=0)
    files_processed: int = Field(default=0, ge=0)
    files_skipped: int = Field(default=0, ge=0)
    files_failed: int = Field(default=0, ge=0)
    sequences: int = Field(default=0, ge=0)


class JobRecord(BaseModel):
    """Полное сохраняемое описание одной job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=200)
    selection: JobSelection
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: JobCounts = Field(default_factory=JobCounts)
    failure_reason: str | None = None


class _RegistryDocument(BaseModel):
    """Внутренний формат единственного файла реестра."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=REGISTRY_VERSION)
    jobs: list[JobRecord] = Field(default_factory=list)


class JobRegistry:
    """Хранит job и создаёт их каталоги только внутри ``jobs_root``.

    Экземпляр не принимает от вызывающего кода пути для отдельных job: идентификатор
    создаётся как UUID, а путь вычисляется исключительно из настроенного jobs-root.
    """

    def __init__(self, jobs_root: Path | None = None) -> None:
        configured_root = jobs_root if jobs_root is not None else get_settings().jobs_root
        self._jobs_root = Path(configured_root)
        self._registry_path = self._jobs_root / REGISTRY_FILENAME
        self._lock = RLock()

    @property
    def jobs_root(self) -> Path:
        """Возвращает настроенный корень, в котором допускается запись результатов."""

        return self._jobs_root

    def create(self, name: str, selection: JobSelection | Mapping[str, JsonValue]) -> JobRecord:
        """Создаёт запись queued-job и её изолированный UUID-каталог."""

        validated_name = self._validate_name(name)
        validated_selection = self._validate_selection(selection)
        with self._lock:
            self._ensure_jobs_root()
            document = self._read_document()
            job_id = str(uuid4())
            job_directory = self._job_directory(job_id)
            try:
                job_directory.mkdir(mode=0o750)
            except OSError as error:
                raise JobRegistryError("Не удалось создать каталог новой job.") from error

            now = _utc_now()
            record = JobRecord(
                id=job_id,
                name=validated_name,
                selection=validated_selection,
                status=JobStatus.QUEUED,
                created_at=now,
                updated_at=now,
            )
            document.jobs.append(record)
            try:
                self._write_document(document)
            except Exception:
                # Пустой каталог не является опубликованной job; убрать его можно
                # только пока он создан данным вызовом и ещё не попал в реестр.
                try:
                    job_directory.rmdir()
                except OSError:
                    pass
                raise
            return record

    def list(self) -> tuple[JobRecord, ...]:
        """Возвращает все job в порядке их добавления в реестр."""

        with self._lock:
            if not self._jobs_root.exists():
                return ()
            return tuple(self._read_document().jobs)

    def get(self, job_id: str | UUID) -> JobRecord:
        """Возвращает job по UUID или сообщает о её отсутствии."""

        normalized_id = self._normalize_job_id(job_id)
        with self._lock:
            if not self._jobs_root.exists():
                raise JobNotFoundError("Job с указанным идентификатором не найдена.")
            document = self._read_document()
            _, record = self._find_record(document, normalized_id)
            return record

    def directory_for(self, job_id: str | UUID) -> Path:
        """Возвращает каталог существующей job внутри настроенного jobs-root."""

        normalized_id = self._normalize_job_id(job_id)
        self.get(normalized_id)
        return self._job_directory(normalized_id)

    def update_status(
        self,
        job_id: str | UUID,
        status: JobStatus | str,
        *,
        counts: JobCounts | Mapping[str, int] | None = None,
        failure_reason: str | None = None,
    ) -> JobRecord:
        """Меняет статус job только по разрешённому графу переходов."""

        normalized_id = self._normalize_job_id(job_id)
        target_status = self._normalize_status(status)
        validated_counts = self._validate_counts(counts) if counts is not None else None
        validated_reason = self._validate_failure_reason(failure_reason)
        with self._lock:
            document = self._read_document()
            index, current = self._find_record(document, normalized_id)
            if target_status not in ALLOWED_TRANSITIONS[current.status]:
                raise JobStatusTransitionError(
                    "Недопустимый переход статуса job: "
                    f"{current.status.value} → {target_status.value}."
                )

            now = _utc_now()
            changes: dict[str, object] = {
                "status": target_status,
                "updated_at": now,
            }
            if target_status is JobStatus.RUNNING:
                changes["started_at"] = now
            if target_status in TERMINAL_STATUSES:
                changes["finished_at"] = now
            if validated_counts is not None:
                changes["counts"] = validated_counts
            if failure_reason is not None:
                changes["failure_reason"] = validated_reason

            updated = current.model_copy(update=changes)
            document.jobs[index] = updated
            self._write_document(document)
            return updated

    def recover_interrupted_running(self) -> tuple[JobRecord, ...]:
        """Переводит сохранившиеся running-job в failed после рестарта приложения."""

        with self._lock:
            if not self._jobs_root.exists():
                return ()
            document = self._read_document()
            now = _utc_now()
            recovered: list[JobRecord] = []
            for index, current in enumerate(document.jobs):
                if current.status is not JobStatus.RUNNING:
                    continue
                updated = current.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": now,
                        "finished_at": now,
                        "failure_reason": INTERRUPTED_REASON,
                    }
                )
                document.jobs[index] = updated
                recovered.append(updated)
            if recovered:
                self._write_document(document)
            return tuple(recovered)

    def delete_terminal(self, job_ids: Sequence[str | UUID]) -> tuple[str, ...]:
        """Удаляет завершённые job из реестра и их UUID-каталоги результатов."""

        try:
            normalized_ids = tuple(self._normalize_job_id(job_id) for job_id in job_ids)
        except TypeError as error:
            raise JobRegistryError("Для удаления необходимо передать список идентификаторов job.") from error
        if not normalized_ids:
            raise JobRegistryError("Не выбраны job для удаления.")
        if len(normalized_ids) != len(set(normalized_ids)):
            raise JobRegistryError("Список job для удаления содержит повторяющиеся идентификаторы.")

        with self._lock:
            self._ensure_jobs_root()
            document = self._read_document()
            records = [self._find_record(document, job_id)[1] for job_id in normalized_ids]
            nonterminal = next(
                (record for record in records if record.status not in TERMINAL_STATUSES),
                None,
            )
            if nonterminal is not None:
                raise JobRegistryError(
                    f"Удалять можно только завершённые job. Job «{nonterminal.name}» ещё выполняется."
                )

            directories = [self._safe_job_directory_for_deletion(job_id) for job_id in normalized_ids]
            try:
                for directory in directories:
                    shutil.rmtree(directory)
            except OSError as error:
                raise JobRegistryError("Не удалось удалить каталог выбранной job.") from error

            removed_ids = set(normalized_ids)
            document.jobs = [record for record in document.jobs if record.id not in removed_ids]
            self._write_document(document)
            return normalized_ids

    def _ensure_jobs_root(self) -> None:
        """Создаёт только настроенный корень результатов, если он отсутствует."""

        try:
            self._jobs_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        except OSError as error:
            raise JobRegistryError("Не удалось подготовить каталог результатов job.") from error
        if not self._jobs_root.is_dir() or self._jobs_root.is_symlink():
            raise JobRegistryError("Каталог результатов job недоступен или небезопасен.")

    def _read_document(self) -> _RegistryDocument:
        """Читает реестр и преобразует повреждение в понятную диагностику."""

        if not self._registry_path.exists():
            return _RegistryDocument()
        if self._registry_path.is_symlink() or not self._registry_path.is_file():
            raise JobRegistryError("Файл реестра job недоступен или небезопасен.")
        try:
            with self._registry_path.open("r", encoding="utf-8") as registry_file:
                raw_document = json.load(registry_file)
            document = _RegistryDocument.model_validate(raw_document)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise JobRegistryError(
                "Реестр job повреждён или имеет неподдерживаемый формат."
            ) from error
        if document.version != REGISTRY_VERSION:
            raise JobRegistryError("Версия реестра job не поддерживается.")
        self._validate_unique_ids(document)
        return document

    def _write_document(self, document: _RegistryDocument) -> None:
        """Атомарно заменяет реестр временным файлом в том же jobs-root."""

        self._ensure_jobs_root()
        if self._registry_path.exists() and self._registry_path.is_symlink():
            raise JobRegistryError("Файл реестра job недоступен или небезопасен.")
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._jobs_root,
                prefix=".jobs_registry_",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    document.model_dump(mode="json"),
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self._registry_path)
        except (OSError, TypeError, ValueError) as error:
            try:
                if "temporary_path" in locals() and temporary_path.exists():
                    temporary_path.unlink()
            except OSError:
                pass
            raise JobRegistryError("Не удалось сохранить реестр job.") from error

    def _job_directory(self, job_id: str) -> Path:
        """Собирает путь UUID-каталога, который не может покинуть jobs-root."""

        normalized_id = self._normalize_job_id(job_id)
        return self._jobs_root / normalized_id

    def _safe_job_directory_for_deletion(self, job_id: str) -> Path:
        """Проверяет UUID-каталог перед рекурсивным удалением."""

        root = self._jobs_root.resolve()
        if self._jobs_root.is_symlink() or not root.is_dir():
            raise JobRegistryError("Каталог результатов job недоступен или небезопасен.")

        directory = root / self._normalize_job_id(job_id)
        if directory.is_symlink() or not directory.is_dir():
            raise JobRegistryError("Каталог выбранной job недоступен или небезопасен.")
        resolved_directory = directory.resolve()
        if not resolved_directory.is_relative_to(root) or resolved_directory.parent != root:
            raise JobRegistryError("Каталог выбранной job выходит за пределы каталога результатов.")
        return directory

    @staticmethod
    def _validate_name(name: str) -> str:
        """Проверяет пользовательское название job без неявного изменения текста."""

        if not isinstance(name, str) or not name.strip():
            raise JobRegistryError("Название job должно быть непустой строкой.")
        if len(name) > 200:
            raise JobRegistryError("Название job не должно превышать 200 символов.")
        return name

    @staticmethod
    def _validate_selection(
        selection: JobSelection | Mapping[str, JsonValue],
    ) -> JobSelection:
        """Принимает только JSON-сериализуемый структурированный выбор."""

        try:
            return (
                selection
                if isinstance(selection, JobSelection)
                else JobSelection.model_validate(dict(selection))
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise JobRegistryError("Выбор для job должен быть JSON-сериализуемым объектом.") from error

    @staticmethod
    def _validate_counts(
        counts: JobCounts | Mapping[str, int],
    ) -> JobCounts:
        """Проверяет итоговые счётчики перед их сохранением."""

        try:
            return counts if isinstance(counts, JobCounts) else JobCounts.model_validate(dict(counts))
        except (TypeError, ValueError, ValidationError) as error:
            raise JobRegistryError("Счётчики job имеют недопустимый формат.") from error

    @staticmethod
    def _validate_failure_reason(failure_reason: str | None) -> str | None:
        """Ограничивает причину сбоя текстовым JSON-значением."""

        if failure_reason is not None and not isinstance(failure_reason, str):
            raise JobRegistryError("Причина сбоя job должна быть строкой.")
        return failure_reason

    @staticmethod
    def _normalize_job_id(job_id: str | UUID) -> str:
        """Принимает только канонический UUID, исключая пути и иные строки."""

        try:
            parsed_id = UUID(str(job_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise JobRegistryError("Идентификатор job должен быть UUID.") from error
        if str(parsed_id) != str(job_id).lower():
            raise JobRegistryError("Идентификатор job должен быть UUID в канонической форме.")
        return str(parsed_id)

    @staticmethod
    def _normalize_status(status: JobStatus | str) -> JobStatus:
        """Преобразует строковый статус в известное значение перечисления."""

        try:
            return JobStatus(status)
        except (TypeError, ValueError) as error:
            raise JobRegistryError("Указан неизвестный статус job.") from error

    @staticmethod
    def _find_record(document: _RegistryDocument, job_id: str) -> tuple[int, JobRecord]:
        """Ищет уникальную запись job в документе реестра."""

        for index, record in enumerate(document.jobs):
            if record.id == job_id:
                return index, record
        raise JobNotFoundError("Job с указанным идентификатором не найдена.")

    @staticmethod
    def _validate_unique_ids(document: _RegistryDocument) -> None:
        """Не допускает неоднозначный реестр с повторяющимися идентификаторами."""

        identifiers = [record.id for record in document.jobs]
        if len(identifiers) != len(set(identifiers)):
            raise JobRegistryError("Реестр job содержит повторяющиеся идентификаторы.")


_registry: JobRegistry | None = None
_registry_lock = RLock()


def get_job_registry() -> JobRegistry:
    """Возвращает общий реестр для настроенного корня результатов."""

    global _registry
    settings = get_settings()
    with _registry_lock:
        if _registry is None or _registry.jobs_root != settings.jobs_root:
            _registry = JobRegistry(settings.jobs_root)
        return _registry


def _utc_now() -> datetime:
    """Фиксирует время в UTC для сериализуемых метаданных job."""

    return datetime.now(timezone.utc)
