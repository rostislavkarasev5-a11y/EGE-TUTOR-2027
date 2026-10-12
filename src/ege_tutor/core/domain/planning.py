"""Расписание, план на день, дисциплина и контрольная «я это знаю» (Phase 7, ADR-0019).

Расписание ученика — личные данные: хранится только в базе, не в Git (ADR-0004).
"""

import datetime as dt
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject

WEEKDAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


@dataclass(frozen=True)
class CalendarWindow:
    """Окно для учёбы в шаблоне недели: день недели (0 — понедельник) и время «с–до»."""

    id: int
    weekday: int
    start: dt.time
    end: dt.time

    @property
    def minutes(self) -> int:
        return _minute(self.end) - _minute(self.start)

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.weekday]


def _minute(t: dt.time) -> int:
    return t.hour * 60 + t.minute


class EventKind(StrEnum):
    SCHOOL = "SCHOOL"
    TRAINING = "TRAINING"
    COMPETITION = "COMPETITION"
    TRIP = "TRIP"
    REST = "REST"
    ILLNESS = "ILLNESS"
    OTHER = "OTHER"


EVENT_KIND_NAMES: dict[EventKind, str] = {
    EventKind.SCHOOL: "школа",
    EventKind.TRAINING: "тренировка",
    EventKind.COMPETITION: "соревнование",
    EventKind.TRIP: "поездка",
    EventKind.REST: "отдых",
    EventKind.ILLNESS: "болезнь",
    EventKind.OTHER: "другое",
}


@dataclass(frozen=True)
class CalendarEvent:
    """Событие. Время — местное время ученика (без часового пояса)."""

    id: int
    kind: EventKind
    title: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    blocks_study: bool

    @property
    def kind_name(self) -> str:
        return EVENT_KIND_NAMES[self.kind]


@dataclass(frozen=True)
class DailyCheckin:
    day: dt.date
    fatigue: int  # 1 — бодр, 5 — очень устал
    available_minutes: int | None  # сколько реально есть времени; None — не указано
    note: str | None


@dataclass(frozen=True)
class DayBudget:
    """Сколько минут на учёбу сегодня и почему."""

    day: dt.date
    minutes: int
    window_minutes: int
    blocked_minutes: int
    fatigue_factor: float
    template_empty: bool
    lines: tuple[str, ...]

    @property
    def day_off(self) -> bool:
        return self.minutes == 0


class PlanItemKind(StrEnum):
    DIAGNOSTIC = "DIAGNOSTIC"
    REVIEW = "REVIEW"
    MISTAKE = "MISTAKE"
    PRACTICE = "PRACTICE"
    CONTROL = "CONTROL"


PLAN_ITEM_KIND_NAMES: dict[PlanItemKind, str] = {
    PlanItemKind.DIAGNOSTIC: "диагностика",
    PlanItemKind.REVIEW: "повторение",
    PlanItemKind.MISTAKE: "задачи на ошибку",
    PlanItemKind.PRACTICE: "тренировка",
    PlanItemKind.CONTROL: "контрольная",
}


class PlanItemStatus(StrEnum):
    """Состояние пункта. Выполнение (DONE/PARTIAL/MISSED) считается по попыткам, не хранится."""

    PLANNED = "PLANNED"
    DONE = "DONE"
    PARTIAL = "PARTIAL"
    MISSED = "MISSED"
    MOVED = "MOVED"  # перенесён учеником на другой день
    EXCUSED = "EXCUSED"  # объективная причина
    REMOVED = "REMOVED"  # дополнительный пункт убран учеником


PLAN_ITEM_STATUS_NAMES: dict[PlanItemStatus, str] = {
    PlanItemStatus.PLANNED: "в плане",
    PlanItemStatus.DONE: "выполнено",
    PlanItemStatus.PARTIAL: "частично",
    PlanItemStatus.MISSED: "не выполнено",
    PlanItemStatus.MOVED: "перенесено",
    PlanItemStatus.EXCUSED: "объективная причина",
    PlanItemStatus.REMOVED: "убрано",
}

# Состояния, которые задаёт ученик; остальные вычисляются.
USER_STATUSES = frozenset({PlanItemStatus.MOVED, PlanItemStatus.EXCUSED, PlanItemStatus.REMOVED})


@dataclass(frozen=True)
class PlanItem:
    id: int
    day: dt.date
    position: int
    kind: PlanItemKind
    subject: Subject
    exam_item: int | None
    skill_code: str | None
    tasks: int  # сколько задач решить (для диагностики — 1: завершить её)
    minutes: int
    mandatory: bool
    added_by_user: bool
    stored_status: PlanItemStatus  # PLANNED или статус, заданный учеником
    reason: str  # почему пункт в плане
    note: str | None  # причина переноса или объективная причина
    carried_from: dt.date | None  # перенесён с этого дня
    done_tasks: int = 0  # сколько уже сделано (считается по попыткам)
    day_over: bool = False  # день закончился

    @property
    def kind_name(self) -> str:
        return PLAN_ITEM_KIND_NAMES[self.kind]

    @property
    def status(self) -> PlanItemStatus:
        if self.stored_status in USER_STATUSES:
            return self.stored_status
        if self.done_tasks >= self.tasks:
            return PlanItemStatus.DONE
        if self.day_over:
            return PlanItemStatus.PARTIAL if self.done_tasks else PlanItemStatus.MISSED
        return PlanItemStatus.PARTIAL if self.done_tasks else PlanItemStatus.PLANNED

    @property
    def status_name(self) -> str:
        return PLAN_ITEM_STATUS_NAMES[self.status]

    @property
    def active(self) -> bool:
        """Пункт ещё в плане этого дня (не перенесён, не убран, не снят причиной)."""
        return self.stored_status not in USER_STATUSES

    @property
    def done_share(self) -> float:
        return min(self.done_tasks, self.tasks) / self.tasks if self.tasks else 0.0

    @property
    def open(self) -> bool:
        return self.active and self.done_tasks < self.tasks and not self.day_over

    def with_progress(self, done_tasks: int, day_over: bool) -> "PlanItem":
        return replace(self, done_tasks=done_tasks, day_over=day_over)


@dataclass(frozen=True)
class DailyPlan:
    day: dt.date
    built_at: dt.datetime
    budget_minutes: int
    explanation: str
    items: tuple[PlanItem, ...] = field(default=())

    @property
    def active_items(self) -> tuple[PlanItem, ...]:
        return tuple(i for i in self.items if i.active)

    @property
    def mandatory_minutes(self) -> int:
        return sum(i.minutes for i in self.active_items if i.mandatory)

    @property
    def mandatory_done_minutes(self) -> float:
        return sum(i.minutes * i.done_share for i in self.active_items if i.mandatory)

    @property
    def mandatory_count(self) -> int:
        return sum(1 for i in self.active_items if i.mandatory)

    @property
    def mandatory_done_count(self) -> int:
        return sum(1 for i in self.active_items if i.mandatory and i.done_share >= 1)


class DisciplineColor(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


DISCIPLINE_COLOR_NAMES: dict[DisciplineColor, str] = {
    DisciplineColor.GREEN: "зелёный",
    DisciplineColor.YELLOW: "жёлтый",
    DisciplineColor.ORANGE: "оранжевый",
    DisciplineColor.RED: "красный",
}


@dataclass(frozen=True)
class DisciplineDay:
    """Итог закрытого дня: сохраняется один раз и задним числом не пересчитывается."""

    day: dt.date
    due_minutes: int  # минуты выполнимых обязательных пунктов
    done_minutes: float
    due_items: int
    done_items: int
    excused: bool  # в этот день была объективная причина

    @property
    def counted(self) -> bool:
        return self.due_minutes > 0

    @property
    def share(self) -> float | None:
        return self.done_minutes / self.due_minutes if self.due_minutes else None


@dataclass(frozen=True)
class DisciplineReport:
    color: DisciplineColor | None  # None — пока не было ни одного дня с планом
    share: float | None
    days_counted: int
    due_items: int
    done_items: int
    missed_streak: int
    excuse_days: int
    excuses_frequent: bool
    message: str
    days: tuple[DisciplineDay, ...]

    @property
    def color_name(self) -> str:
        return DISCIPLINE_COLOR_NAMES[self.color] if self.color else "нет данных"


class ControlStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"


CONTROL_STATUS_NAMES: dict[ControlStatus, str] = {
    ControlStatus.ACTIVE: "идёт",
    ControlStatus.PASSED: "засчитана",
    ControlStatus.FAILED: "не засчитана",
}


@dataclass(frozen=True)
class ControlSession:
    """Контрольная «я это знаю» по номеру ЕГЭ: без подсказок и без ИИ."""

    id: int
    subject: Subject
    exam_item: int
    status: ControlStatus
    task_ids: tuple[int, ...]
    started_at: dt.datetime
    finished_at: dt.datetime | None
    time_limit_seconds: int  # сумма нормативов (для справки)
    passed_tasks: int  # верно, самостоятельно и вовремя
    total_tasks: int

    @property
    def status_name(self) -> str:
        return CONTROL_STATUS_NAMES[self.status]


@dataclass(frozen=True)
class ControlTaskResult:
    task_id: int
    attempt_id: int | None
    correct: bool
    independent: bool
    in_time: bool
    seconds: int | None
    norm_seconds: int | None

    @property
    def passed(self) -> bool:
        return self.correct and self.independent and self.in_time
