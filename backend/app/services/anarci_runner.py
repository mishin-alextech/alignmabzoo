"""Изолированный запуск ANARCI и проверка его зависимостей."""

from __future__ import annotations

import re
import shutil
import subprocess
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence


SchemeName = Literal["imgt", "kabat", "chothia"]
ANARCI_SCHEMES: tuple[SchemeName, ...] = ("imgt", "kabat", "chothia")
ANARCI_SPECIES: dict[str, str] = {
    "Ms": "mouse",
    "Rb": "rabbit",
    "Rt": "rat",
    "Pg": "pig",
    "Hu": "human",
    "Cm": "alpaca",
    "Bv": "cow",
}
REQUIRED_EXECUTABLES: tuple[str, ...] = ("ANARCI", "hmmscan", "clustalo")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Полный результат внешней команды для будущего append-only лога job."""

    command: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Показывает успешное завершение дочернего процесса."""

        return self.returncode == 0 and self.error is None


@dataclass(frozen=True, slots=True)
class RuntimeCheck:
    """Результат проверки исполняемых файлов в окружении контейнера."""

    missing: tuple[str, ...]

    @property
    def is_available(self) -> bool:
        """Все необходимые исполняемые файлы найдены в ``PATH``."""

        return not self.missing

    @property
    def error(self) -> str | None:
        """Возвращает понятную для пользователя русскоязычную ошибку."""

        if self.is_available:
            return None
        return "Окружение обработки неисправно: не найдены команды " + ", ".join(self.missing) + "."


@dataclass(frozen=True, slots=True)
class AnarciSchemeResult:
    """Итог одного запуска ANARCI для схемы нумерации."""

    scheme: SchemeName
    output_path: Path
    command_result: CommandResult | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """CSV создан командой без непредвиденной ошибки."""

        return self.error is None and self.command_result is not None and self.command_result.succeeded


@dataclass(frozen=True, slots=True)
class AnarciSequenceResult:
    """Сводка трёх запусков ANARCI для одной последовательности."""

    sequence_name: str
    results: tuple[AnarciSchemeResult, ...]
    environment_error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Все требуемые CSV получены успешно."""

        return self.environment_error is None and all(item.succeeded for item in self.results)


def check_runtime_environment() -> RuntimeCheck:
    """Проверяет ANARCI, HMMER и Clustal Omega без выполнения команд."""

    missing = tuple(command for command in REQUIRED_EXECUTABLES if shutil.which(command) is None)
    return RuntimeCheck(missing=missing)


def build_anarci_command(
    sequence: str,
    scheme: SchemeName,
    animal_code: str,
    output_path: str | Path,
) -> tuple[str, ...]:
    """Строит точную команду ANARCI для одного нативного CSV."""

    if scheme not in ANARCI_SCHEMES:
        raise ValueError(f"Неизвестная схема ANARCI: {scheme}")
    command: list[str] = [
        "ANARCI",
        "-i",
        _validate_sequence(sequence),
        "--scheme",
        scheme,
        "--csv",
        "--outfile",
        str(output_path),
    ]
    species = ANARCI_SPECIES.get(animal_code)
    if species is not None:
        command.extend(("--use_species", species))
    return tuple(command)


def run_anarci_for_sequence(
    *,
    sequence_name: str,
    sequence: str,
    animal_code: str,
    job_directory: str | Path,
    jobs_root: str | Path,
) -> AnarciSequenceResult:
    """Запускает ANARCI для трёх схем и возвращает ошибки структурированно.

    Функция не выбрасывает ошибку отдельной последовательности: будущий
    job-слой может записать её в ``report.json`` и завершить job как
    ``partial``. Единственные создаваемые артефакты находятся в
    ``<job_directory>/anarci``.
    """

    resolved_job = validate_job_directory(job_directory, jobs_root)
    environment = _check_anarci_environment()
    output_directory = job_child_path(resolved_job, "anarci")
    output_directory.mkdir(parents=True, exist_ok=True)
    safe_name = safe_artifact_stem(sequence_name)

    if not environment.is_available:
        return AnarciSequenceResult(
            sequence_name=sequence_name,
            environment_error=environment.error,
            results=tuple(
                AnarciSchemeResult(
                    scheme=scheme,
                    output_path=output_directory / f"{safe_name}_{scheme}.csv",
                    command_result=None,
                    error=environment.error,
                )
                for scheme in ANARCI_SCHEMES
            ),
        )

    try:
        clean_sequence = _validate_sequence(sequence)
    except ValueError as error:
        message = str(error)
        return AnarciSequenceResult(
            sequence_name=sequence_name,
            results=tuple(
                AnarciSchemeResult(
                    scheme=scheme,
                    output_path=output_directory / f"{safe_name}_{scheme}.csv",
                    command_result=None,
                    error=message,
                )
                for scheme in ANARCI_SCHEMES
            ),
        )

    results: list[AnarciSchemeResult] = []
    for scheme in ANARCI_SCHEMES:
        output_path = output_directory / f"{safe_name}_{scheme}.csv"
        native_output_root = job_child_path(
            resolved_job,
            "anarci",
            f".{safe_name}_{scheme}_{uuid4().hex}",
        )
        command = build_anarci_command(
            clean_sequence,
            scheme,
            animal_code,
            native_output_root,
        )
        command_result = _run_command(command, cwd=resolved_job)
        normalisation_error: str | None = None
        if command_result.succeeded:
            normalisation_error = _move_native_csv_output(
                native_output_root=native_output_root,
                output_path=output_path,
                job_directory=resolved_job,
            )
        error = normalisation_error or _anarci_result_error(command_result, output_path)
        results.append(
            AnarciSchemeResult(
                scheme=scheme,
                output_path=output_path,
                command_result=command_result,
                error=error,
            )
        )
    return AnarciSequenceResult(sequence_name=sequence_name, results=tuple(results))


def validate_job_directory(job_directory: str | Path, jobs_root: str | Path) -> Path:
    """Разрешает только существующий каталог конкретной job внутри jobs-root."""

    root = Path(jobs_root).resolve(strict=False)
    job = Path(job_directory).resolve(strict=False)
    try:
        relative = job.relative_to(root)
    except ValueError as error:
        raise ValueError("Каталог job должен находиться внутри корня результатов job") from error
    if not relative.parts:
        raise ValueError("Для артефактов требуется каталог конкретной job, а не общий jobs-root")
    return job


def safe_artifact_stem(sequence_name: str) -> str:
    """Создаёт безопасный компонент имени CSV, не допуская выхода из job."""

    stem = _UNSAFE_FILENAME.sub("_", sequence_name.strip()).strip("._")
    if not stem:
        raise ValueError("Имя последовательности не подходит для имени артефакта")
    return stem[:180]


def job_child_path(job_directory: str | Path, *parts: str) -> Path:
    """Возвращает путь артефакта, не позволяя symlink выйти из job-каталога."""

    job = Path(job_directory).resolve(strict=False)
    artifact = job.joinpath(*parts).resolve(strict=False)
    try:
        artifact.relative_to(job)
    except ValueError as error:
        raise ValueError("Путь артефакта не должен выходить за пределы каталога job") from error
    return artifact


def _check_anarci_environment() -> RuntimeCheck:
    required = ("ANARCI", "hmmscan")
    return RuntimeCheck(tuple(command for command in required if shutil.which(command) is None))


def _validate_sequence(sequence: str) -> str:
    cleaned = "".join(sequence.split()).upper()
    if not cleaned:
        raise ValueError("Невозможно запустить ANARCI для пустой последовательности")
    if not cleaned.isascii() or not cleaned.isalpha():
        raise ValueError("Последовательность для ANARCI содержит недопустимые символы")
    return cleaned


def _run_command(command: Sequence[str], *, cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return CommandResult(tuple(command), None, error=f"Не удалось запустить ANARCI: {error}")
    return CommandResult(
        tuple(command),
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _anarci_result_error(result: CommandResult, output_path: Path) -> str | None:
    if result.error is not None:
        return result.error
    if result.returncode != 0:
        details = " ".join(result.stderr.split())[:500]
        return "ANARCI завершился с ошибкой" + (f": {details}" if details else "")
    if not output_path.is_file():
        return "ANARCI завершился без создания ожидаемого CSV"
    return None


def _normalise_csv_output(output_path: Path) -> None:
    """Приводит различия выпусков ANARCI к обязательному имени артефакта.

    Часть выпусков добавляет ``.csv`` к значению ``--outfile`` даже при уже
    указанном расширении. Оба пути остаются внутри ``anarci`` конкретной job;
    после успешного запуска сохраняется единый требуемый путь.
    """

    if output_path.is_file():
        return
    appended_suffix = output_path.with_name(output_path.name + ".csv")
    if appended_suffix.is_file():
        appended_suffix.replace(output_path)


def _move_native_csv_output(
    *,
    native_output_root: Path,
    output_path: Path,
    job_directory: Path,
) -> str | None:
    """Переименовывает единственный нативный CSV ANARCI в артефакт job.

    Bundled ANARCI создаёт ``<outfile>_<H|K|L>.csv``. Уникальный корень
    создаётся для одного вызова, поэтому CSV, оставшийся от другого запуска,
    не может быть ошибочно принят за текущий результат.
    """

    output_directory = native_output_root.parent
    try:
        job_child_path(job_directory, "anarci", native_output_root.name)
        job_child_path(job_directory, "anarci", output_path.name)
    except ValueError:
        return "Небезопасный путь результата ANARCI"

    prefix = f"{native_output_root.name}_"
    generated = tuple(
        candidate
        for candidate in output_directory.iterdir()
        if candidate.is_file() and not candidate.is_symlink() and candidate.name.startswith(prefix)
    )
    expected_names = {
        f"{native_output_root.name}_{chain_type}.csv" for chain_type in ("H", "K", "L")
    }
    expected = tuple(candidate for candidate in generated if candidate.name in expected_names)
    unexpected = tuple(candidate for candidate in generated if candidate.name not in expected_names)

    if unexpected:
        return "ANARCI создал неожиданные файлы результата"
    if not expected:
        return "ANARCI завершился без создания нативного CSV"
    if len(expected) != 1:
        return "ANARCI создал несколько нативных CSV; тип цепи определить нельзя"

    try:
        expected[0].replace(output_path)
    except OSError as error:
        return f"Не удалось сохранить CSV ANARCI: {error}"
    return None
