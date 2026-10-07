"""Каталог: структура экзамена, темы и навыки."""

from dataclasses import dataclass, field
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject


class AnswerKind(StrEnum):
    """Форма ответа на задание экзамена."""

    SHORT = "short"  # краткий ответ (число, строка)
    EXTENDED = "extended"  # развёрнутое решение (часть 2 математики)


@dataclass(frozen=True)
class ExamSpecItem:
    number: int
    title: str
    part: int
    answer_kind: AnswerKind
    max_points: int
    time_norm_seconds: int  # оценка проекта, а не ФИПИ (см. ExamSpec.time_norm_source)


@dataclass(frozen=True)
class ExamSpec:
    """Структура экзамена. status = provisional, пока не сверена с демоверсией нужного года."""

    subject: Subject
    exam_year: int
    status: str
    source: str
    duration_minutes: int
    items: tuple[ExamSpecItem, ...]
    time_norm_source: str

    @property
    def max_primary_score(self) -> int:
        return sum(item.max_points for item in self.items)

    def item(self, number: int) -> ExamSpecItem | None:
        return next((i for i in self.items if i.number == number), None)


@dataclass(frozen=True)
class Skill:
    code: str
    title: str
    exam_items: tuple[int, ...]
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Topic:
    code: str
    subject: Subject
    title: str
    exam_items: tuple[int, ...]
    skills: tuple[Skill, ...] = field(default=())


@dataclass(frozen=True)
class Catalog:
    """Весь каталог: структуры экзаменов и темы обоих предметов."""

    specs: dict[Subject, ExamSpec]
    topics: tuple[Topic, ...]

    def topics_of(self, subject: Subject) -> tuple[Topic, ...]:
        return tuple(t for t in self.topics if t.subject == subject)

    def skill_codes(self, subject: Subject) -> set[str]:
        return {s.code for t in self.topics_of(subject) for s in t.skills}
