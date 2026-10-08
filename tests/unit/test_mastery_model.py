"""Свойства Mastery v0 (ADR-0006, ADR-0015): проверяем свойства, а не конкретные числа."""

import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from ege_tutor.config import load_settings
from ege_tutor.core.domain import Attempt, AttemptMode, AttemptStatus, Subject, Verdict
from ege_tutor.core.services.mastery_model import MasteryModelV0

CONFIG = load_settings().mastery
MODEL = MasteryModelV0(CONFIG)
START = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)


def attempt(
    i: int = 1,
    *,
    correct: bool = True,
    hint: int = 0,
    spent: int = 60,
    norm: int | None = 300,
    attempt_no: int = 1,
    mode: AttemptMode = AttemptMode.PRACTICE,
    day: float = 0.0,
    gave_up: bool = False,
) -> Attempt:
    finished = START + dt.timedelta(days=day)
    return Attempt(
        id=i,
        task_id=i,
        subject=Subject.MATH_PROFILE,
        exam_item=6,
        mode=mode,
        attempt_no=attempt_no,
        status=AttemptStatus.GAVE_UP if gave_up else AttemptStatus.ANSWERED,
        started_at=finished - dt.timedelta(seconds=spent),
        finished_at=finished,
        answer=None if gave_up else "1",
        verdict=None if gave_up else (Verdict.CORRECT if correct else Verdict.WRONG),
        max_hint_level=hint,
        time_norm_seconds=norm,
    )


attempts = st.builds(
    attempt,
    correct=st.booleans(),
    hint=st.integers(0, 4),
    spent=st.integers(1, 5000),
    norm=st.one_of(st.none(), st.integers(30, 1200)),
    attempt_no=st.integers(1, 6),
    mode=st.sampled_from(list(AttemptMode)),
    gave_up=st.booleans(),
)


@given(attempts, st.one_of(st.none(), st.integers(1, 5)))
def test_evidence_in_unit_interval_and_weight_positive(a, difficulty):
    e, w = MODEL.evidence(a, difficulty)
    assert 0.0 <= e <= 1.0
    assert w > 0


@given(st.lists(attempts, min_size=1, max_size=12), st.floats(0, 400))
def test_mastery_stays_in_unit_interval(history, days_later):
    timed = [
        attempt(i, correct=a.correct, hint=a.max_hint_level, day=i * 0.7, gave_up=a.verdict is None)
        for i, a in enumerate(history, start=1)
    ]
    state = MODEL.state([(a, 3) for a in timed])
    assert state is not None
    assert 0.0 <= state.value_raw <= 1.0
    assert 0.0 <= state.confidence < 1.0
    later = state.last_practiced_at + dt.timedelta(days=days_later)
    value = MODEL.forgotten(state, later)
    assert 0.0 <= value <= state.value_raw  # забывание никогда не увеличивает M


@given(st.integers(1, 4))
def test_hint_never_beats_independent_solution(hint):
    independent, _ = MODEL.evidence(attempt(hint=0), 3)
    hinted, _ = MODEL.evidence(attempt(hint=hint), 3)
    assert hinted < independent
    base = [attempt(1, correct=False)]
    m_ind = MODEL.state([(a, 3) for a in [*base, attempt(2, day=1)]]).value_raw
    m_hint = MODEL.state([(a, 3) for a in [*base, attempt(2, day=1, hint=hint)]]).value_raw
    assert m_hint < m_ind


def test_full_solution_shown_gives_no_credit():
    e, _ = MODEL.evidence(attempt(hint=4), 3)
    assert e == 0.0


def test_slow_and_repeated_attempts_count_less():
    fast, _ = MODEL.evidence(attempt(spent=60, norm=300), 3)
    slow, _ = MODEL.evidence(attempt(spent=900, norm=300), 3)
    again, _ = MODEL.evidence(attempt(attempt_no=3), 3)
    assert slow < fast
    assert again < fast


def test_difficulty_and_mode_only_change_weight():
    e_easy, w_easy = MODEL.evidence(attempt(), 1)
    e_hard, w_hard = MODEL.evidence(attempt(), 5)
    e_mock, w_mock = MODEL.evidence(attempt(mode=AttemptMode.MOCK), 3)
    e_prac, w_prac = MODEL.evidence(attempt(), 3)
    assert e_easy == e_hard == e_mock == e_prac
    assert w_hard > w_easy
    assert w_mock > w_prac


def test_recent_attempts_matter_more():
    old_good = MODEL.state([(attempt(1), 3), (attempt(2, correct=False, day=1), 3)])
    old_bad = MODEL.state([(attempt(1, correct=False), 3), (attempt(2, day=1), 3)])
    assert old_bad.value_raw > old_good.value_raw


def test_spaced_success_grows_stability_and_failure_shrinks_it():
    spaced = MODEL.state([(attempt(i, day=i * 2), 3) for i in range(1, 4)])
    same_day = MODEL.state([(attempt(i, day=i * 0.01), 3) for i in range(1, 4)])
    assert spaced.stability_days > same_day.stability_days
    failed = MODEL.state(
        [*[(attempt(i, day=i * 2), 3) for i in range(1, 4)], (attempt(9, correct=False, day=10), 3)]
    )
    assert failed.stability_days < spaced.stability_days
    assert failed.stability_days >= CONFIG.forgetting.initial_stability_days


def test_confidence_grows_with_evidence():
    one = MODEL.state([(attempt(1), 3)])
    many = MODEL.state([(attempt(i, day=i), 3) for i in range(1, 8)])
    assert many.confidence > one.confidence


def test_next_review_is_when_forecast_drops_below_threshold():
    state = MODEL.state([(attempt(1), 3)])
    review = MODEL.next_review(state)
    threshold = CONFIG.forgetting.review_threshold
    day_before = dt.datetime.combine(review, dt.time(), dt.UTC) - dt.timedelta(days=1)
    assert MODEL.forgotten(state, day_before) >= threshold
    weak = MODEL.state([(attempt(1, correct=False), 3)])
    assert MODEL.next_review(weak) == weak.last_practiced_at.date()


def test_abandoned_attempts_are_not_evidence():
    abandoned = attempt(1)
    abandoned = Attempt(**{**abandoned.__dict__, "status": AttemptStatus.ABANDONED})
    assert MODEL.state([(abandoned, 3)]) is None
