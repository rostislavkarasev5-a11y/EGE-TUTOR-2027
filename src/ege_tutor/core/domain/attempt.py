"""Попытки решения, подсказки и проверка ответа (Phase 2)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.subject import Subject


class AttemptMode(StrEnum):
    """Режим работы. Влияет на вес попытки в mastery (config/mastery.toml, Phase 4)."""

    PRACTICE = "PRACTICE"
    HOMEWORK = "HOMEWORK"
    REVIEW = "REVIEW"
    CONTROL = "CONTROL"
    DIAGNOSTIC = "DIAGNOSTIC"
    MOCK = "MOCK"
    EXAM = "EXAM"


class AttemptStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    ANSWERED = "ANSWERED"  # дан ответ, он проверен
    GAVE_UP = "GAVE_UP"  # сдался без ответа
    ABANDONED = "ABANDONED"  # вышел, не ответив (или программа закрылась)


class Verdict(StrEnum):
    CORRECT = "CORRECT"
    WRONG = "WRONG"
    WRONG_FORMAT = "WRONG_FORMAT"  # значение верное, но на бланке ЕГЭ так записать нельзя


@dataclass(frozen=True)
class AnswerCheck:
    """Результат проверки ответа предметным модулем."""

    verdict: Verdict
    normalized: str  # как программа поняла ответ
    explanation: str = ""

    @property
    def correct(self) -> bool:
        return self.verdict == Verdict.CORRECT


@dataclass(frozen=True)
class Attempt:
    """Одна попытка ответить на задачу. Никогда не удаляется (принцип 3)."""

    id: int
    task_id: int
    subject: Subject
    exam_item: int
    mode: AttemptMode
    attempt_no: int  # какая по счёту попытка на эту задачу
    status: AttemptStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None
    answer: str | None
    verdict: Verdict | None
    max_hint_level: int  # 0 — без подсказок; 4 — видел полное решение
    time_norm_seconds: int | None

    @property
    def correct(self) -> bool:
        return self.verdict == Verdict.CORRECT

    @property
    def independent(self) -> bool:
        """Самостоятельно: верно и без единой подсказки (архитектура, раздел 5.3)."""
        return self.correct and self.max_hint_level == 0

    @property
    def time_spent_seconds(self) -> int | None:
        if self.finished_at is None:
            return None
        return max(0, round((self.finished_at - self.started_at).total_seconds()))

    @property
    def within_norm(self) -> bool | None:
        spent = self.time_spent_seconds
        if spent is None or self.time_norm_seconds is None:
            return None
        return spent <= self.time_norm_seconds


@dataclass(frozen=True)
class HintEvent:
    attempt_id: int
    level: int
    shown_at: dt.datetime
