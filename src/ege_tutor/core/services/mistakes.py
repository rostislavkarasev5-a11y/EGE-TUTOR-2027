"""Ошибки: классификация правилами и паттерны (архитектура, раздел 5.5, ADR-0015).

Правила грубые и честно об этом говорят уверенностью. Пользователь может уточнить категорию;
ИИ-классификация появится в Phase 6 и тоже будет только предложением (CORE решает).
"""

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

from ege_tutor.config import MistakesConfig
from ege_tutor.core.domain import (
    Attempt,
    AttemptStatus,
    CodeRun,
    CodeVerdict,
    Mistake,
    MistakeCategory,
    MistakeDraft,
    MistakePattern,
    Task,
    Verdict,
)

_DAY = 86_400.0


def is_mistake(attempt: Attempt) -> bool:
    """Ошибка — неверный ответ, неверный формат или «сдался»."""
    if attempt.status == AttemptStatus.GAVE_UP:
        return True
    return attempt.status == AttemptStatus.ANSWERED and attempt.verdict in (
        Verdict.WRONG,
        Verdict.WRONG_FORMAT,
    )


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _digits(text: str) -> str:
    return "".join(sorted(ch for ch in text if ch.isdigit()))


def _power_of_ten(ratio: float) -> bool:
    if ratio <= 0:
        return False
    exponent = math.log10(ratio)
    return round(exponent) != 0 and abs(exponent - round(exponent)) < 1e-9


def classify(attempt: Attempt, task: Task, last_run: CodeRun | None) -> MistakeDraft:
    """Категория ошибки по правилам ADR-0015 (первое подходящее правило)."""
    if attempt.verdict == Verdict.WRONG_FORMAT:
        return MistakeDraft(
            MistakeCategory.FORMATTING, 0.9, "значение верное, но так на бланке ЕГЭ не записать"
        )
    if last_run is not None and last_run.verdict != CodeVerdict.OK:
        if last_run.verdict == CodeVerdict.SYNTAX_ERROR:
            return MistakeDraft(MistakeCategory.SYNTAX, 0.9, "синтаксическая ошибка в программе")
        if last_run.verdict == CodeVerdict.TIME_LIMIT:
            return MistakeDraft(
                MistakeCategory.ALGORITHM,
                0.6,
                "программа не уложилась во время — нужен алгоритм быстрее",
            )
        return MistakeDraft(
            MistakeCategory.PROGRAMMING, 0.6, "программа падала или давала неверный вывод на тестах"
        )
    if attempt.status == AttemptStatus.ANSWERED:
        given, expected = _number(attempt.answer), _number(task.answer)
        if given is not None and expected is not None and expected != 0:
            if given == -expected:
                return MistakeDraft(MistakeCategory.CARELESS, 0.6, "ответ отличается только знаком")
            same_digits = (
                attempt.answer is not None
                and task.answer is not None
                and _digits(attempt.answer) == _digits(task.answer)
                and given != expected
            )
            if (given != 0 and _power_of_ten(given / expected)) or same_digits:
                return MistakeDraft(
                    MistakeCategory.ARITHMETIC,
                    0.4,
                    "похоже на ошибку в вычислениях: те же цифры или сдвиг запятой",
                )
    spent, norm = attempt.time_spent_seconds, attempt.time_norm_seconds
    if spent is not None and norm and spent > 2 * norm:
        return MistakeDraft(MistakeCategory.TIME, 0.4, "решение заняло больше двух нормативов")
    if attempt.status == AttemptStatus.GAVE_UP:
        return MistakeDraft(MistakeCategory.TOPIC_GAP, 0.5, "сдался — тему стоит повторить")
    return MistakeDraft(MistakeCategory.TOPIC_GAP, 0.3, "причина неясна — уточни, что пошло не так")


def pattern_priority(
    category: MistakeCategory,
    occurrences: int,
    last_at: dt.datetime,
    config: MistakesConfig,
    now: dt.datetime,
) -> float:
    """база_категории × (1 + 0.5 × (повторов − 1)) × свежесть (архитектура, раздел 5.5)."""
    days = max(0.0, (now - last_at).total_seconds() / _DAY)
    priority = (
        config.category_base[category]
        * (1 + 0.5 * (occurrences - 1))
        * math.exp(-days / config.freshness_days)
    )
    return round(priority, 4)


@dataclass(frozen=True)
class _Event:
    at: dt.datetime
    order: int
    mistake: MistakeCategory | None  # None — самостоятельное верное решение
    breaks_streak: bool


def build_patterns(
    skill_code: str,
    mistakes: Sequence[Mistake],
    attempts: Sequence[Attempt],
    config: MistakesConfig,
    now: dt.datetime,
) -> list[MistakePattern]:
    """Паттерны ошибок навыка, выведенные из истории (их всегда можно пересчитать).

    mistakes — текущие ошибки навыка, attempts — завершённые попытки на задачи с навыком.
    """
    mistake_attempts = {m.attempt_id for m in mistakes}
    events: list[_Event] = []
    for m in mistakes:
        events.append(_Event(m.created_at, m.attempt_id, m.category, True))
    for a in attempts:
        if a.finished_at is None or a.id in mistake_attempts:
            continue
        if a.independent:
            events.append(_Event(a.finished_at, a.id, None, False))
        elif a.status in (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP):
            events.append(_Event(a.finished_at, a.id, None, True))  # верно, но с подсказкой
    events.sort(key=lambda e: (e.at, e.order, e.mistake is None))

    state: dict[MistakeCategory, dict] = {}
    for event in events:
        if event.mistake is not None:
            p = state.setdefault(event.mistake, {"count": 0, "first": event.at, "closed": None})
            p["count"] += 1
            p["last"] = event.at
            p["closed"] = None  # новая ошибка снова открывает паттерн
            for other in state.values():
                other.update(streak=0, streak_day=None)
            continue
        for p in state.values():
            if p["closed"] is not None:
                continue
            if event.breaks_streak:
                p.update(streak=0, streak_day=None)
            elif p.get("streak_day") != event.at.date():
                p["streak"] = p.get("streak", 0) + 1
                p["streak_day"] = event.at.date()
                if p["streak"] >= config.close_after_independent:
                    p["closed"] = event.at

    patterns = []
    for category, p in state.items():
        priority = pattern_priority(category, p["count"], p["last"], config, now)
        patterns.append(
            MistakePattern(
                skill_code=skill_code,
                category=category,
                occurrences=p["count"],
                first_at=p["first"],
                last_at=p["last"],
                independent_streak=p.get("streak", 0),
                closed_at=p["closed"],
                priority=priority if p["closed"] is None else 0.0,
            )
        )
    return sorted(patterns, key=lambda x: -x.priority)
