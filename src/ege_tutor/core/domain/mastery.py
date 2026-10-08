"""Освоение навыков, ошибки и повторения (Phase 4, ADR-0006, ADR-0015)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject


@dataclass(frozen=True)
class SkillMastery:
    """Оценка навыка по модели. value — с учётом забывания на дату as_of."""

    skill_code: str
    model_version: str
    value: float  # M на дату as_of, 0..1
    value_raw: float  # M_raw без забывания
    confidence: float  # 0..1: мало попыток — низкая уверенность
    stability_days: float
    attempts: int
    last_practiced_at: dt.datetime
    next_review_on: dt.date
    as_of: dt.date

    @property
    def review_due(self) -> bool:
        return self.next_review_on <= self.as_of


@dataclass(frozen=True)
class MasteryAggregate:
    """Освоение темы или номера задания ЕГЭ как агрегат его навыков (ADR-0015)."""

    key: str  # код темы или номер задания
    title: str
    subject: Subject
    value: float | None  # None — ни один навык ещё не изучен
    confidence: float
    studied: int  # сколько навыков изучено
    total: int


@dataclass(frozen=True)
class MasterySnapshot:
    snapshot_date: dt.date
    skill_code: str
    model_version: str
    value: float
    value_raw: float
    confidence: float


@dataclass(frozen=True)
class Prediction:
    """Что модель предсказала перед попыткой и что вышло (данные для калибровки)."""

    attempt_id: int
    model_version: str
    predicted: float
    outcome: int | None  # 1 — решено самостоятельно, 0 — нет, None — ещё не известно
    created_at: dt.datetime


class MistakeCategory(StrEnum):
    TOPIC_GAP = "TOPIC_GAP"
    FORMULA = "FORMULA"
    CONDITION = "CONDITION"
    ALGORITHM = "ALGORITHM"
    CARELESS = "CARELESS"
    ARITHMETIC = "ARITHMETIC"
    PROGRAMMING = "PROGRAMMING"
    SYNTAX = "SYNTAX"
    TIME = "TIME"
    FORMATTING = "FORMATTING"
    STRATEGY = "STRATEGY"


MISTAKE_CATEGORY_NAMES: dict[MistakeCategory, str] = {
    MistakeCategory.TOPIC_GAP: "незнание темы",
    MistakeCategory.FORMULA: "формула",
    MistakeCategory.CONDITION: "непонимание условия",
    MistakeCategory.ALGORITHM: "алгоритм",
    MistakeCategory.CARELESS: "невнимательность",
    MistakeCategory.ARITHMETIC: "арифметика",
    MistakeCategory.PROGRAMMING: "программирование",
    MistakeCategory.SYNTAX: "синтаксис",
    MistakeCategory.TIME: "не хватило времени",
    MistakeCategory.FORMATTING: "оформление ответа",
    MistakeCategory.STRATEGY: "стратегия",
}


class ClassifiedBy(StrEnum):
    RULE = "RULE"
    AI = "AI"
    USER = "USER"


@dataclass(frozen=True)
class MistakeDraft:
    """Предложенная классификация ошибки (правилом, позже — ИИ)."""

    category: MistakeCategory
    confidence: float
    description: str
    classified_by: ClassifiedBy = ClassifiedBy.RULE


@dataclass(frozen=True)
class Mistake:
    """Ошибка в попытке по одному навыку. Не удаляется; уточнение — новая запись."""

    id: int
    attempt_id: int
    task_id: int
    skill_code: str | None
    category: MistakeCategory
    classified_by: ClassifiedBy
    confidence: float
    description: str
    created_at: dt.datetime
    is_current: bool  # False — заменена уточнением пользователя

    @property
    def category_name(self) -> str:
        return MISTAKE_CATEGORY_NAMES[self.category]


@dataclass(frozen=True)
class MistakePattern:
    """Повторяющаяся ошибка: навык + категория (архитектура, раздел 5.5)."""

    skill_code: str
    category: MistakeCategory
    occurrences: int
    first_at: dt.datetime
    last_at: dt.datetime
    independent_streak: int  # самостоятельных верных подряд в разные дни после последней ошибки
    closed_at: dt.datetime | None
    priority: float

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def category_name(self) -> str:
        return MISTAKE_CATEGORY_NAMES[self.category]


class ReviewReason(StrEnum):
    FORGETTING = "FORGETTING"  # подошёл срок повторения
    MISTAKES = "MISTAKES"  # открытый паттерн ошибок


@dataclass(frozen=True)
class ReviewItem:
    """Элемент очереди повторений (ADR-0015)."""

    skill_code: str
    skill_title: str
    subject: Subject
    reason: ReviewReason
    value: float | None  # текущий M навыка
    due_on: dt.date | None
    category: MistakeCategory | None = None
    priority: float | None = None


@dataclass(frozen=True)
class MasteryRecord:
    """Сохранённое состояние навыка (без забывания: его считают на нужную дату)."""

    skill_code: str
    model_version: str
    value_raw: float
    confidence: float
    stability_days: float
    attempts: int
    last_practiced_at: dt.datetime
    next_review_on: dt.date
    updated_at: dt.datetime
