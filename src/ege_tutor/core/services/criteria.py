"""Критерии самопроверки части 2 из content/exam_specs/2027/criteria/ (ADR-0022, п. 5).

Файл на предмет (сейчас только math_profile.yaml; у информатики части 2 нет). Каждое задание
проверяется при загрузке: номер — задание с развёрнутым ответом из структуры экзамена,
max_points совпадает со структурой, уровни покрывают каждый балл от max_points до 0 ровно один
раз. Ошибка останавливает загрузку: лучше сразу узнать, чем оценивать по неверным критериям.
Нет папки или файла — не ошибка: тогда самопроверка идёт по общему списку «N из M баллов».
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ege_tutor.core.domain import (
    AnswerKind,
    Catalog,
    CriterionLevel,
    Part2Criteria,
    Subject,
    generic_criteria,
)
from ege_tutor.core.services.catalog import EXAM_YEAR

CRITERIA_DIR = Path("exam_specs") / str(EXAM_YEAR) / "criteria"


class CriteriaError(Exception):
    """Ошибка в файле критериев."""


@dataclass(frozen=True)
class CriteriaLibrary:
    """Критерии по заданиям и максимальные баллы всех заданий с развёрнутым ответом."""

    by_item: dict[tuple[Subject, int], Part2Criteria] = field(default_factory=dict)
    extended: dict[tuple[Subject, int], int] = field(default_factory=dict)

    def get(self, subject: Subject, exam_item: int) -> Part2Criteria | None:
        """Критерии задания; общий список, если файла нет; None — у задания краткий ответ."""
        found = self.by_item.get((subject, exam_item))
        if found is not None:
            return found
        max_points = self.extended.get((subject, exam_item))
        if max_points is None:
            return None
        return generic_criteria(subject, exam_item, max_points)

    def __len__(self) -> int:
        return len(self.by_item)


def _extended_items(catalog: Catalog) -> dict[tuple[Subject, int], int]:
    return {
        (subject, item.number): item.max_points
        for subject, spec in catalog.specs.items()
        for item in spec.items
        if item.answer_kind == AnswerKind.EXTENDED
    }


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: нужен непустой текст")
    return value.strip()


def _item(raw: object, subject: Subject, extended: dict, source: str, note: str) -> Part2Criteria:
    if not isinstance(raw, dict):
        raise ValueError("задание должно быть словарём")
    number = raw.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("number — целое число")
    where = f"задание №{number}"
    expected = extended.get((subject, number))
    if expected is None:
        raise ValueError(f"{where}: это не задание с развёрнутым ответом")
    max_points = raw.get("max_points")
    if max_points != expected:
        raise ValueError(f"{where}: max_points {max_points}, а в структуре экзамена {expected}")
    levels_raw = raw.get("levels")
    if not isinstance(levels_raw, list) or not levels_raw:
        raise ValueError(f"{where}: нет уровней (levels)")
    levels = []
    for n, level in enumerate(levels_raw, 1):
        if not isinstance(level, dict):
            raise ValueError(f"{where}, уровень {n}: ожидается словарь")
        points = level.get("points")
        if not isinstance(points, int) or isinstance(points, bool):
            raise ValueError(f"{where}, уровень {n}: points — целое число")
        levels.append(CriterionLevel(points, _text(level.get("text"), f"{where}, уровень {n}")))
    points_list = sorted((lv.points for lv in levels), reverse=True)
    if points_list != list(range(expected, -1, -1)):
        raise ValueError(
            f"{where}: уровни должны покрывать каждый балл от {expected} до 0 ровно один раз"
        )
    tips_raw = raw.get("tips") or []
    if not isinstance(tips_raw, list):
        raise ValueError(f"{where}: tips — список")
    tips = tuple(_text(t, f"{where}, совет") for t in tips_raw)
    return Part2Criteria(
        subject=subject,
        exam_item=number,
        max_points=expected,
        levels=tuple(sorted(levels, key=lambda lv: -lv.points)),
        tips=tips,
        source=source,
        note=note,
    )


def parse_criteria(data: object, extended: dict[tuple[Subject, int], int]) -> list[Part2Criteria]:
    if not isinstance(data, dict):
        raise ValueError("ожидается словарь верхнего уровня")
    try:
        subject = Subject(data.get("subject"))
    except ValueError:
        raise ValueError(f"неизвестный предмет: {data.get('subject')}") from None
    source = _text(data.get("source"), "source")
    note = str(data.get("note") or "").strip()
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("нет заданий (items)")
    parsed = [_item(raw, subject, extended, source, note) for raw in items]
    numbers = [c.exam_item for c in parsed]
    if len(numbers) != len(set(numbers)):
        raise ValueError("номер задания повторяется")
    return parsed


def load_criteria(content_dir: Path, catalog: Catalog) -> CriteriaLibrary:
    extended = _extended_items(catalog)
    folder = content_dir / CRITERIA_DIR
    by_item: dict[tuple[Subject, int], Part2Criteria] = {}
    if folder.is_dir():
        for path in sorted(folder.glob("*.yaml")):
            try:
                parsed = parse_criteria(yaml.safe_load(path.read_text(encoding="utf-8")), extended)
            except (ValueError, yaml.YAMLError) as e:
                raise CriteriaError(f"ошибка в {path.name}: {e}") from e
            for criteria in parsed:
                key = (criteria.subject, criteria.exam_item)
                if key in by_item:
                    raise CriteriaError(f"{path.name}: задание №{key[1]} уже описано")
                by_item[key] = criteria
    return CriteriaLibrary(by_item, extended)
