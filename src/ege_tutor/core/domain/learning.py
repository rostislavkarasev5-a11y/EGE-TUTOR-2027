"""Учебный цикл по навыку: теория, примеры, самостоятельные, разбор, домашка (Phase 8, ADR-0022)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject


class LessonStep(StrEnum):
    THEORY = "THEORY"
    EXAMPLES = "EXAMPLES"
    INDEPENDENT = "INDEPENDENT"
    CHECK = "CHECK"
    MISTAKE_REVIEW = "MISTAKE_REVIEW"
    MISTAKE_TASKS = "MISTAKE_TASKS"
    HOMEWORK = "HOMEWORK"
    DONE = "DONE"


LESSON_STEPS: tuple[LessonStep, ...] = tuple(LessonStep)

LESSON_STEP_NAMES: dict[LessonStep, str] = {
    LessonStep.THEORY: "теория",
    LessonStep.EXAMPLES: "примеры",
    LessonStep.INDEPENDENT: "самостоятельные",
    LessonStep.CHECK: "проверка",
    LessonStep.MISTAKE_REVIEW: "разбор ошибок",
    LessonStep.MISTAKE_TASKS: "задачи на ошибки",
    LessonStep.HOMEWORK: "домашка",
    LessonStep.DONE: "готово",
}


class LessonStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    ABANDONED = "ABANDONED"


LESSON_STATUS_NAMES: dict[LessonStatus, str] = {
    LessonStatus.ACTIVE: "идёт",
    LessonStatus.DONE: "пройден",
    LessonStatus.ABANDONED: "брошен",
}


class LessonTaskRole(StrEnum):
    """Для какого шага блока решалась задача."""

    INDEPENDENT = "INDEPENDENT"
    MISTAKE = "MISTAKE"
    HOMEWORK = "HOMEWORK"


# Шаги с задачами и роль их попыток.
STEP_ROLES: dict[LessonStep, LessonTaskRole] = {
    LessonStep.INDEPENDENT: LessonTaskRole.INDEPENDENT,
    LessonStep.MISTAKE_TASKS: LessonTaskRole.MISTAKE,
    LessonStep.HOMEWORK: LessonTaskRole.HOMEWORK,
}


@dataclass(frozen=True)
class Lesson:
    id: int
    subject: Subject
    skill_code: str
    step: LessonStep
    status: LessonStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None
    # Навыки, в которых были ошибки (заполняются на шаге «проверка»).
    mistake_skills: tuple[str, ...] = ()
    homework_due: dt.date | None = None

    @property
    def step_name(self) -> str:
        return LESSON_STEP_NAMES[self.step]

    @property
    def status_name(self) -> str:
        return LESSON_STATUS_NAMES[self.status]

    @property
    def step_number(self) -> int:
        """Номер шага от 1 (для «шаг 3 из 7»; «готово» шагом не считается)."""
        return LESSON_STEPS.index(self.step) + 1


@dataclass(frozen=True)
class LessonTask:
    """Попытка, сделанная в учебном блоке."""

    attempt_id: int
    task_id: int
    role: LessonTaskRole
    finished: bool
    correct: bool
    independent: bool
    reviewed: bool  # ошибка разобрана на шаге «разбор ошибок»

    @property
    def problem(self) -> bool:
        """Попытка, которую нужно разобрать: неверно, сдался или решено с подсказкой."""
        return self.finished and not (self.correct and self.independent)


@dataclass(frozen=True)
class LessonCheck:
    """Итог самостоятельных задач."""

    total: int
    good: int  # верно и без подсказок
    share: float | None
    passed: bool
    problems: tuple[int, ...]  # попытки для разбора


@dataclass(frozen=True)
class LessonProgress:
    """Где ученик сейчас: шаг, сколько задач шага сделано и сколько нужно."""

    lesson: Lesson
    done: int
    target: int
    short: bool  # задач на навык меньше, чем нужно по правилам
    open_attempt_id: int | None


@dataclass(frozen=True)
class LessonSuggestion:
    """Учебный блок для плана на день: продолжить начатый или начать новый."""

    subject: Subject
    skill_code: str
    lesson: Lesson | None
    reason: str
    tasks: int  # сколько задач осталось на ближайшем шаге с задачами
    reading_minutes: int  # время на теорию и примеры, если они впереди


@dataclass(frozen=True)
class TheoryExample:
    title: str
    statement: str
    solution: str
    answer: str


@dataclass(frozen=True)
class Theory:
    """Теория навыка из content/theory/. Пишет Claude, проверяется тестами (ADR-0022)."""

    skill_code: str
    title: str
    text: str
    examples: tuple[TheoryExample, ...]
    source: str
    version: int
