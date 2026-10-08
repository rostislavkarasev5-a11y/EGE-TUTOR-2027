"""Классификация ошибок правилами и паттерны ошибок (ADR-0015)."""

import datetime as dt

from ege_tutor.config import load_settings
from ege_tutor.core.domain import (
    AnswerType,
    Attempt,
    AttemptMode,
    AttemptStatus,
    ClassifiedBy,
    CodeRun,
    CodeVerdict,
    Mistake,
    MistakeCategory,
    Subject,
    Task,
    TaskSource,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.services.mistakes import build_patterns, classify, is_mistake

CONFIG = load_settings().mastery.mistakes
T0 = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)
TASK = Task(
    id=1,
    subject=Subject.MATH_PROFILE,
    exam_item=6,
    statement="x",
    answer_type=AnswerType.NUMBER,
    answer="12.5",
    solution=None,
    difficulty=3,
    time_norm_seconds=300,
    source=TaskSource.USER_MATERIAL,
    source_ref="тест",
    source_version=None,
    verification_status=VerificationStatus.REVIEWED,
    skills=("M06.algebraic",),
    assets=(),
    content_hash="h",
    import_batch_id=None,
    created_at=T0,
)


def attempt(
    answer: str | None = "7",
    verdict: Verdict | None = Verdict.WRONG,
    *,
    i: int = 1,
    day: float = 0,
    spent: int = 60,
    hint: int = 0,
    gave_up: bool = False,
) -> Attempt:
    finished = T0 + dt.timedelta(days=day)
    return Attempt(
        id=i,
        task_id=1,
        subject=Subject.MATH_PROFILE,
        exam_item=6,
        mode=AttemptMode.PRACTICE,
        attempt_no=1,
        status=AttemptStatus.GAVE_UP if gave_up else AttemptStatus.ANSWERED,
        started_at=finished - dt.timedelta(seconds=spent),
        finished_at=finished,
        answer=None if gave_up else answer,
        verdict=None if gave_up else verdict,
        max_hint_level=hint,
        time_norm_seconds=300,
    )


def run(verdict: CodeVerdict) -> CodeRun:
    return CodeRun(1, 1, 1, T0, "print()", verdict, 0, 0, None, "", "", 1, 0.1)


def category(a: Attempt, last_run: CodeRun | None = None) -> MistakeCategory:
    return classify(a, TASK, last_run).category


def test_what_counts_as_mistake():
    assert is_mistake(attempt())
    assert is_mistake(attempt(verdict=Verdict.WRONG_FORMAT))
    assert is_mistake(attempt(gave_up=True))
    assert not is_mistake(attempt("12.5", Verdict.CORRECT))


def test_rules_in_order():
    assert category(attempt("12,50", Verdict.WRONG_FORMAT)) == MistakeCategory.FORMATTING
    assert category(attempt(), run(CodeVerdict.SYNTAX_ERROR)) == MistakeCategory.SYNTAX
    assert category(attempt(), run(CodeVerdict.TIME_LIMIT)) == MistakeCategory.ALGORITHM
    assert category(attempt(), run(CodeVerdict.WRONG_ANSWER)) == MistakeCategory.PROGRAMMING
    assert category(attempt(), run(CodeVerdict.OK)) == MistakeCategory.TOPIC_GAP
    assert category(attempt("-12.5")) == MistakeCategory.CARELESS
    assert category(attempt("125")) == MistakeCategory.ARITHMETIC
    assert category(attempt("1.25")) == MistakeCategory.ARITHMETIC
    assert category(attempt("21.5")) == MistakeCategory.ARITHMETIC
    assert category(attempt(spent=700)) == MistakeCategory.TIME
    assert category(attempt(gave_up=True)) == MistakeCategory.TOPIC_GAP
    unknown = classify(attempt("abc"), TASK, None)
    assert unknown.category == MistakeCategory.TOPIC_GAP
    assert unknown.confidence < classify(attempt(gave_up=True), TASK, None).confidence
    assert unknown.classified_by == ClassifiedBy.RULE


def mistake(i: int, cat: MistakeCategory, day: float) -> Mistake:
    return Mistake(
        i,
        i,
        1,
        "M06.algebraic",
        cat,
        ClassifiedBy.RULE,
        0.5,
        "",
        T0 + dt.timedelta(days=day),
        True,
    )


def test_pattern_counts_and_priority_grow_with_repeats():
    now = T0 + dt.timedelta(days=3)
    one = build_patterns(
        "M06.algebraic", [mistake(1, MistakeCategory.ARITHMETIC, 0)], [], CONFIG, now
    )
    two = build_patterns(
        "M06.algebraic",
        [mistake(1, MistakeCategory.ARITHMETIC, 0), mistake(2, MistakeCategory.ARITHMETIC, 1)],
        [],
        CONFIG,
        now,
    )
    assert one[0].occurrences == 1 and two[0].occurrences == 2
    assert two[0].priority > one[0].priority
    stale = build_patterns(
        "M06.algebraic",
        [mistake(1, MistakeCategory.ARITHMETIC, 0)],
        [],
        CONFIG,
        T0 + dt.timedelta(days=60),
    )
    assert stale[0].priority < one[0].priority


def test_pattern_closes_after_independent_solutions_on_different_days():
    mistakes = [mistake(1, MistakeCategory.ARITHMETIC, 0)]
    good = [attempt("12.5", Verdict.CORRECT, i=10 + d, day=d) for d in (1, 2, 3)]
    same_day = [attempt("12.5", Verdict.CORRECT, i=20 + k, day=1 + k * 0.01) for k in range(3)]
    now = T0 + dt.timedelta(days=5)
    closed = build_patterns("M06.algebraic", mistakes, good, CONFIG, now)[0]
    assert not closed.is_open and closed.priority == 0
    still_open = build_patterns("M06.algebraic", mistakes, same_day, CONFIG, now)[0]
    assert still_open.is_open and still_open.independent_streak == 1
    hinted = [*good[:2], attempt("12.5", Verdict.CORRECT, i=30, day=2.5, hint=1), good[2]]
    assert build_patterns("M06.algebraic", mistakes, hinted, CONFIG, now)[0].is_open
    reopened = build_patterns(
        "M06.algebraic", [*mistakes, mistake(40, MistakeCategory.ARITHMETIC, 4)], good, CONFIG, now
    )[0]
    assert reopened.is_open and reopened.occurrences == 2
