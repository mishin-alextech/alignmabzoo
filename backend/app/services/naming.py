"""Детерминированное извлечение идентификатора клона и типа цепи без I/O."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final, Literal


ChainGroup = Literal["VHeavy", "VHH", "VKappa", "VLambda", "Other"]


_PROJECT_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(r"-\d")
_ALPHANUMERIC_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")
_CHAIN_ALIASES: Final[dict[str, ChainGroup]] = {
    "HC": "VHeavy",
    "VH": "VHeavy",
    "HeavyC": "VHeavy",
    "VHeavy": "VHeavy",
    "VHH": "VHH",
    "VK": "VKappa",
    "VK1": "VKappa",
    "V1K": "VKappa",
    "K1C": "VKappa",
    "KC": "VKappa",
    "KC1": "VKappa",
    "kappa1": "VKappa",
    "Kappa": "VKappa",
    "Kappa1": "VKappa",
    "KappaC": "VKappa",
    "VKappa": "VKappa",
    "LC": "VLambda",
    "LC1": "VLambda",
    "LC2": "VLambda",
    "VLambda": "VLambda",
}
_CHAIN_ALIAS_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(
        re.escape(alias) for alias in sorted(_CHAIN_ALIASES, key=len, reverse=True)
    ) + r")(?![A-Za-z0-9])"
)


@dataclass(frozen=True, slots=True)
class NamingResult:
    """Нормализованное имя одной последовательности и сведения о его получении."""

    name: str
    group: ChainGroup
    source_stem: str
    project_base: str
    clone: str
    diagnostic: str | None = None

    @property
    def display_name(self) -> str:
        """Возвращает стабильный идентификатор, предназначенный для FASTA и UI."""

        return self.name


def name_chain(animal_code: str, project_name: str, source_name: str) -> NamingResult:
    """Строит идентификатор цепи из имени проекта и пути либо имени входного файла.

    Поиск клона выполняется в строгом порядке: полное основание проекта, его
    сокращение с совпадением двух из первых трёх символов, затем код животного.
    Все сопоставления чувствительны к регистру. Функция не читает и не изменяет
    файлы: диагностическое сообщение должен записать вызывающий job-слой.
    """

    source_stem = _source_stem(source_name)
    project_base = _PROJECT_SUFFIX_RE.split(project_name, maxsplit=1)[0]
    project_base = _without_animal_prefix(project_base, animal_code)

    clone, clone_diagnostic = _extract_clone(source_stem, project_base, animal_code)
    group = _detect_group(source_stem)
    chain_diagnostic = (
        "Не удалось определить тип цепи по имени файла "
        f"«{source_stem}»; последовательность помещена в группу Other."
        if group == "Other"
        else None
    )
    diagnostic = _combine_diagnostics(clone_diagnostic, chain_diagnostic)
    return NamingResult(
        name=f"{group}_{clone}",
        group=group,
        source_stem=source_stem,
        project_base=project_base,
        clone=clone,
        diagnostic=diagnostic,
    )


def _source_stem(source_name: str) -> str:
    """Выделяет имя без последнего расширения одинаково для POSIX и Windows пути."""

    filename = source_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    stem, separator, _extension = filename.rpartition(".")
    return stem if separator and stem else filename


def _without_animal_prefix(project_base: str, animal_code: str) -> str:
    """Удаляет отдельный начальный код животного из имени проекта.

    В структуре каталога проекты могут называться ``Cm AFP-L3`` или
    ``Cm_AFP-L3``, хотя код животного уже передан отдельно. Удаляем только
    точный начальный токен с разделителем-пробелом либо ``_``; сравнение
    остаётся чувствительным к регистру.
    """

    if not animal_code:
        return project_base
    marker = re.compile(rf"^{re.escape(animal_code)}(?:[ _]+)(.+)$")
    match = marker.fullmatch(project_base)
    return match.group(1) if match is not None else project_base


def _extract_clone(source_stem: str, project_base: str, animal_code: str) -> tuple[str, str | None]:
    """Извлекает клон в установленном порядке и сохраняет имя при неуспехе."""

    if project_base:
        # Сначала сопоставляем составное имя проекта, считая пробел и "_"
        # эквивалентными разделителями. Это должно предшествовать буквальному
        # поиску: в ``Ov_HBE90001`` буквальное совпадение ``Ov_HBE`` оставляет
        # лишь ``90001``, тогда как клоном является ``HBE90001``.
        clone = _clone_from_separator_flexible_project_name(source_stem, project_base)
        if clone:
            return clone, None

        clone = _clone_from_project_token(source_stem, project_base)
        if clone:
            return clone, None

        position = source_stem.find(project_base)
        if position >= 0:
            clone = _token_after(source_stem, position + len(project_base))
            if clone:
                return clone, None

        clone = _fallback_project_clone(source_stem, project_base)
        if clone:
            return clone, None

    clone = _clone_after_animal_code(source_stem, animal_code)
    if clone:
        return clone, None

    return (
        source_stem,
        "Не удалось выделить клон по имени проекта или коду животного; "
        "в качестве идентификатора сохранено имя файла.",
    )


def _token_after(value: str, position: int) -> str | None:
    """Возвращает ближайший буквенно-цифровой фрагмент после известного маркера."""

    match = _ALPHANUMERIC_RUN_RE.search(value, position)
    candidate = match.group(0) if match is not None else None
    if _has_letter(candidate):
        return candidate
    if candidate is None or not candidate.isdigit() or match is None:
        return None

    preceding_runs = list(_ALPHANUMERIC_RUN_RE.finditer(value, 0, match.start()))
    for preceding in reversed(preceding_runs):
        prefix = preceding.group(0)
        if _has_letter(prefix):
            return f"{prefix}{candidate}"
    return None


def _has_letter(candidate: str | None) -> bool:
    """Проверяет, что кандидат идентификатора клона содержит букву."""

    return candidate is not None and any(character.isalpha() for character in candidate)


def _clone_from_separator_flexible_project_name(
    source_stem: str,
    project_base: str,
) -> str | None:
    """Ищет точное имя проекта, когда пробелы в имени файла заменены подчёркиваниями.

    Последняя часть имени проекта может быть непосредственно продолжена номером
    клона. Например, ``Ov HBE`` в ``VHeavy_cDNA_Ov_HBE90001`` даёт
    ``HBE90001``. Регистр букв и сами части проекта должны совпасть точно.
    """

    parts = [part for part in re.split(r"[ _]+", project_base) if part]
    if len(parts) < 2:
        return None

    prefix = r"[ _]+".join(re.escape(part) for part in parts[:-1])
    final_part = re.escape(parts[-1])
    marker = re.compile(
        rf"(?<![A-Za-z0-9]){prefix}[ _]+({final_part}[A-Za-z0-9]*)"
    )
    match = marker.search(source_stem)
    candidate = match.group(1) if match is not None else None
    return candidate if _has_letter(candidate) else None


def _clone_from_project_token(source_stem: str, project_base: str) -> str | None:
    """Возвращает полный токен, начинающийся с одиночного имени проекта.

    Например, проект ``HBE`` в ``VHeavy_cDNA_Ov_HBE90001`` должен дать
    ``HBE90001``. Поиск выполняется по границам алфавитно-цифрового токена,
    поэтому не принимает частичное совпадение внутри другого идентификатора.
    """

    if not re.fullmatch(r"[A-Za-z0-9]+", project_base):
        return None
    marker = re.compile(
        rf"(?<![A-Za-z0-9])({re.escape(project_base)}[A-Za-z0-9]+)(?![A-Za-z0-9])"
    )
    match = marker.search(source_stem)
    candidate = match.group(1) if match is not None else None
    return candidate if _has_letter(candidate) else None


def _fallback_project_clone(source_stem: str, project_base: str) -> str | None:
    """Ищет фрагмент с двумя символами из первых трёх символов проекта
    в исходном порядке.

    Сокращённый маркер сохраняется в клоне: для ``PTH`` и ``PT92485`` итогом
    будет ``PT92485``, как предписано форматом исходных данных.
    """

    project_prefix = project_base[:3]
    if len(project_prefix) < 2:
        return None
    for run in _ALPHANUMERIC_RUN_RE.finditer(source_stem):
        candidate = run.group(0)
        if _has_letter(candidate) and _matching_prefix_characters(candidate, project_prefix) >= 2:
            return candidate
    return None


def _matching_prefix_characters(candidate: str, project_prefix: str) -> int:
    """Считает совпавшие по порядку символы в начале имени возможного клона."""

    matched = 0
    offset = 0
    for project_character in project_prefix:
        found = candidate.find(project_character, offset)
        if found < 0:
            continue
        matched += 1
        offset = found + 1
    return matched


def _clone_after_animal_code(source_stem: str, animal_code: str) -> str | None:
    """Ищет код животного как отдельный маркер и извлекает следующий фрагмент."""

    if not animal_code:
        return None
    marker = re.compile(r"(?<![A-Za-z0-9])" + re.escape(animal_code) + r"(?![A-Za-z0-9])")
    match = marker.search(source_stem)
    return _token_after(source_stem, match.end()) if match is not None else None


def _detect_group(source_stem: str) -> ChainGroup:
    """Определяет первую указанную в имени цепь с учётом регистра алиасов."""

    match = _CHAIN_ALIAS_RE.search(source_stem)
    return _CHAIN_ALIASES[match.group(1)] if match is not None else "Other"


def _combine_diagnostics(*messages: str | None) -> str | None:
    """Собирает несколько причин в одну запись для журнала валидации."""

    combined = " ".join(message for message in messages if message)
    return combined or None
