"""Адаптивная диагностика: сессии, оценки номеров и прогноз (Phase 5, ADR-0016)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject


class DiagnosticStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    ABANDONED = "ABANDONED"


class StopReason(StrEnum):
    PRECISE = "PRECISE"  # прогноз достаточно точен
    TASK_BUDGET = "TASK_BUDGET"  # решено максимальное число задач
    TIME_BUDGET = "TIME_BUDGET"  # исчерпано время
    NO_GAIN = "NO_GAIN"  # следующие задачи почти ничего не уточняют
    NO_TASKS = "NO_TASKS"  # подходящие задачи закончились
    USER = "USER"  # пользователь завершил сам


STOP_REASON_NAMES: dict[StopReason, str] = {
    StopReason.PRECISE: "прогноз уже достаточно точный",
    StopReason.TASK_BUDGET: "решено максимальное число задач",
    StopReason.TIME_BUDGET: "закончилось время диагностики",
    StopReason.NO_GAIN: "следующие задачи почти ничего не уточнили бы",
    StopReason.NO_TASKS: "проверенные задачи для диагностики закончились",
    StopReason.USER: "ты завершил диагностику сам",
}


class ItemBasis(StrEnum):
    """Как получена оценка номера."""

    DIRECT = "DIRECT"  # были задачи этого номера
    INFERRED = "INFERRED"  # выведено косвенно, через общий уровень по предмету
    NOT_ASSESSED = "NOT_ASSESSED"  # в банке нет проверенных задач этого номера


ITEM_BASIS_NAMES: dict[ItemBasis, str] = {
    ItemBasis.DIRECT: "измерено",
    ItemBasis.INFERRED: "выведено косвенно",
    ItemBasis.NOT_ASSESSED: "не оценён: нет проверенных задач",
}


@dataclass(frozen=True)
class DiagnosticObservation:
    """Ответ на задачу диагностики так, как его видит модель."""

    exam_item: int
    difficulty: int
    correct: bool
    slow: bool  # верно, но дольше 2× норматива


@dataclass(frozen=True)
class ItemEstimate:
    exam_item: int
    title: str
    max_points: int
    probability: float  # P(решу задачу средней сложности этого номера)
    confidence: float  # 0 — ничего не известно, 1 — оценка точная
    basis: ItemBasis
    answered: int  # сколько задач этого номера было в диагностике
    answer_only: bool  # часть 2: оценено по ответу, без проверки оформления


@dataclass(frozen=True)
class Forecast:
    """Прогноз первичного балла с диапазоном."""

    mean: float
    low: float
    high: float
    max_points: int
    interval: float  # какую вероятность покрывает диапазон

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2


@dataclass(frozen=True)
class DiagnosticSession:
    id: int
    subject: Subject
    status: DiagnosticStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None
    stop_reason: StopReason | None
    model_version: str
    forecast: Forecast | None  # сохраняется при завершении


@dataclass(frozen=True)
class DiagnosticItemResult:
    """Сохранённая оценка номера по итогам диагностики (предварительный baseline)."""

    exam_item: int
    probability: float
    confidence: float
    basis: ItemBasis
    answered: int


@dataclass(frozen=True)
class DiagnosticState:
    """Где сейчас диагностика: оценки, прогноз, бюджет."""

    session: DiagnosticSession
    estimates: tuple[ItemEstimate, ...]
    forecast: Forecast
    tasks_done: int
    minutes_spent: float
    max_tasks: int
    max_minutes: int
