"""Модель адаптивной диагностики diag-v0 (ADR-0016): свойства, а не конкретные числа."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ege_tutor.config import load_settings
from ege_tutor.core.domain import DiagnosticObservation
from ege_tutor.core.services.diagnostics_model import DiagnosticModelV0, ItemSpec

MODEL = DiagnosticModelV0(load_settings().diagnostics.model)
ITEMS = (ItemSpec(1, 1), ItemSpec(2, 1), ItemSpec(3, 1), ItemSpec(4, 2))


def obs(item: int, difficulty: int = 3, correct: bool = True, slow: bool = False):
    return DiagnosticObservation(item, difficulty, correct=correct, slow=slow)


def test_probability_grows_with_level_and_falls_with_difficulty():
    assert MODEL.probability(1.0, 3) > MODEL.probability(0.0, 3)
    assert MODEL.probability(0.0, 4) < MODEL.probability(0.0, 2)
    assert MODEL.probability(-50, 5) >= MODEL.config.guess  # угадать можно всегда


def test_prior_forecast_is_symmetric_and_inside_range():
    forecast = MODEL.state(ITEMS, []).forecast(0.8)
    assert forecast.max_points == 5
    assert 0 <= forecast.low < forecast.mean < forecast.high <= 5


def test_correct_answer_raises_own_and_other_items():
    before = MODEL.state(ITEMS, [])
    after = MODEL.state(ITEMS, [obs(1, correct=True)])
    assert after.item_estimate(1)[0] > before.item_estimate(1)[0]
    # связь номеров через общий уровень: остальные тоже растут, но меньше
    grow_other = after.item_estimate(2)[0] - before.item_estimate(2)[0]
    assert 0 < grow_other < after.item_estimate(1)[0] - before.item_estimate(1)[0]


def test_wrong_answer_lowers_estimates():
    before = MODEL.state(ITEMS, [])
    after = MODEL.state(ITEMS, [obs(1, correct=False)])
    assert after.item_estimate(1)[0] < before.item_estimate(1)[0]
    assert after.item_estimate(3)[0] < before.item_estimate(3)[0]


def test_slow_answer_is_weaker_evidence():
    fast = MODEL.state(ITEMS, [obs(1, correct=True)]).item_estimate(1)[0]
    slow = MODEL.state(ITEMS, [obs(1, correct=True, slow=True)]).item_estimate(1)[0]
    prior = MODEL.state(ITEMS, []).item_estimate(1)[0]
    assert prior < slow < fast


def test_solving_hard_task_says_more_than_easy_one():
    easy = MODEL.state(ITEMS, [obs(1, difficulty=1)]).item_estimate(1)[0]
    hard = MODEL.state(ITEMS, [obs(1, difficulty=5)]).item_estimate(1)[0]
    assert hard > easy


def test_answers_increase_confidence_and_narrow_forecast():
    prior = MODEL.state(ITEMS, [])
    answers = [obs(1), obs(1, 4, False), obs(4), obs(2, 2)]
    after = MODEL.state(ITEMS, answers)
    assert after.item_estimate(1)[1] > prior.item_estimate(1)[1]
    assert after.forecast(0.8).half_width < prior.forecast(0.8).half_width


def test_item_with_more_points_is_more_informative():
    state = MODEL.state(ITEMS, [])
    assert state.expected_gain(4, 3) > state.expected_gain(1, 3)


def test_result_is_reproducible():
    answers = [obs(1), obs(2, 4, False)]
    a = MODEL.state(ITEMS, answers).forecast(0.8)
    b = MODEL.state(ITEMS, list(answers)).forecast(0.8)
    assert a == b


observations = st.lists(
    st.builds(
        DiagnosticObservation,
        exam_item=st.sampled_from([1, 2, 3, 4]),
        difficulty=st.integers(1, 5),
        correct=st.booleans(),
        slow=st.booleans(),
    ),
    max_size=12,
)


@settings(max_examples=40, deadline=None)
@given(observations, st.sampled_from([1, 2, 3, 4]), st.integers(1, 5))
def test_estimates_in_range_and_gain_not_negative(answers, item, difficulty):
    state = MODEL.state(ITEMS, answers)
    for spec in ITEMS:
        probability, confidence = state.item_estimate(spec.number)
        assert 0 <= probability <= 1
        assert 0 <= confidence <= 1
    forecast = state.forecast(0.8)
    assert 0 <= forecast.low <= forecast.mean <= forecast.high <= forecast.max_points
    assert state.expected_gain(item, difficulty) >= -1e-9


@pytest.mark.parametrize("interval", [0.5, 0.8, 0.95])
def test_wider_interval_gives_wider_range(interval):
    state = MODEL.state(ITEMS, [obs(1)])
    assert state.forecast(interval).half_width <= state.forecast(0.99).half_width
