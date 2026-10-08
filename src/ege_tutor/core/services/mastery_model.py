"""Mastery v0 — стартовая экспериментальная модель (ADR-0006, ADR-0015).

Чистые функции без базы и без времени «сейчас»: всё, что нужно, передаётся аргументами.
Поэтому модель легко проверять тестами свойств и заменить моделью v1 за тем же интерфейсом.

Свидетельство попытки:  e = правильность × самостоятельность × фактор_времени × фактор_повтора
Вес свидетельства:      w = вес_сложности × вес_режима
"""

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ege_tutor.config import MasteryConfig
from ege_tutor.core.domain import Attempt, AttemptMode, AttemptStatus

_DAY = 86_400.0


@dataclass(frozen=True)
class SkillState:
    """Состояние навыка после всех попыток (без учёта забывания)."""

    value_raw: float
    confidence: float
    stability_days: float
    attempts: int
    last_practiced_at: dt.datetime


class MasteryModel(Protocol):
    """Сменная модель освоения навыка. С каждым значением хранится version."""

    version: str

    def evidence(self, attempt: Attempt, difficulty: int | None) -> tuple[float, float]:
        """Свидетельство e ∈ [0, 1] и вес w > 0 одной завершённой попытки."""
        ...

    def state(self, history: Sequence[tuple[Attempt, int | None]]) -> SkillState | None:
        """Состояние навыка по его попыткам в хронологическом порядке. None — не изучен."""
        ...

    def forgotten(self, state: SkillState, at: dt.datetime) -> float:
        """M на момент at с учётом забывания."""
        ...

    def next_review(self, state: SkillState) -> dt.date:
        """Когда прогноз M опустится ниже порога повторения."""
        ...


def counts_as_evidence(attempt: Attempt) -> bool:
    """Свидетельство дают попытки с ответом и сдачи; брошенные — нет."""
    return attempt.status in (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP) and (
        attempt.finished_at is not None
    )


class MasteryModelV0:
    def __init__(self, config: MasteryConfig) -> None:
        self.config = config
        self.version = config.model_version

    # ── свидетельство ──

    def _time_factor(self, attempt: Attempt) -> float:
        factors = self.config.time_factor
        spent, norm = attempt.time_spent_seconds, attempt.time_norm_seconds
        if spent is None or not norm:
            return factors.within_norm
        if spent <= norm:
            return factors.within_norm
        if spent <= 2 * norm:
            return factors.up_to_double
        return factors.over_double

    def _repeat_factor(self, attempt_no: int) -> float:
        factors = self.config.repeat_factor
        if attempt_no <= 1:
            return factors.first
        if attempt_no == 2:
            return factors.second
        return factors.third_or_later

    def _difficulty_weight(self, difficulty: int | None) -> float:
        return getattr(self.config.difficulty_weight, f"d{difficulty or 3}")

    def _mode_weight(self, mode: AttemptMode) -> float:
        return getattr(self.config.mode_weight, mode.value.lower())

    def evidence(self, attempt: Attempt, difficulty: int | None) -> tuple[float, float]:
        correctness = 1.0 if attempt.correct else 0.0
        independence = self.config.independence.for_hint_level(min(attempt.max_hint_level, 4))
        e = (
            correctness
            * independence
            * self._time_factor(attempt)
            * self._repeat_factor(attempt.attempt_no)
        )
        w = self._difficulty_weight(difficulty) * self._mode_weight(attempt.mode)
        return e, w

    # ── навык ──

    def state(self, history: Sequence[tuple[Attempt, int | None]]) -> SkillState | None:
        attempts = [(a, d) for a, d in history if counts_as_evidence(a)]
        if not attempts:
            return None
        attempts.sort(key=lambda item: (item[0].finished_at, item[0].id))
        forgetting = self.config.forgetting
        decay = self.config.evidence.recency_decay
        stability = forgetting.initial_stability_days
        last: dt.datetime | None = None
        weighted = total = 0.0
        for a, difficulty in attempts:
            e, w = self.evidence(a, difficulty)
            # каждая новая попытка уменьшает вклад предыдущих в recency_decay раз
            weighted = weighted * decay + w * e
            total = total * decay + w
            assert a.finished_at is not None
            if last is not None:
                gap_days = (a.finished_at - last).total_seconds() / _DAY
                if e >= forgetting.success_threshold and gap_days >= forgetting.min_review_gap_days:
                    stability = min(
                        stability * forgetting.stability_growth, forgetting.max_stability_days
                    )
                elif e < forgetting.failure_threshold:
                    stability = max(
                        stability * forgetting.stability_after_failure,
                        forgetting.initial_stability_days,
                    )
            last = a.finished_at
        assert last is not None
        value_raw = weighted / total if total > 0 else 0.0
        confidence = 1.0 - math.exp(-total / self.config.evidence.confidence_scale)
        return SkillState(
            value_raw=min(1.0, max(0.0, value_raw)),
            confidence=confidence,
            stability_days=stability,
            attempts=len(attempts),
            last_practiced_at=last,
        )

    def forgotten(self, state: SkillState, at: dt.datetime) -> float:
        days = max(0.0, (at - state.last_practiced_at).total_seconds() / _DAY)
        return state.value_raw * math.exp(-days / state.stability_days)

    def next_review(self, state: SkillState) -> dt.date:
        threshold = self.config.forgetting.review_threshold
        last_day = state.last_practiced_at.date()
        if state.value_raw <= threshold:
            return last_day
        days = state.stability_days * math.log(state.value_raw / threshold)
        return (state.last_practiced_at + dt.timedelta(days=days)).date()
