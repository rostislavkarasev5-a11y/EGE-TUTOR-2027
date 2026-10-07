"""Mastery, ошибки и повторения вместе с попытками (Phase 4, ADR-0015)."""

import datetime as dt

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import (
    AttemptMode,
    ClassifiedBy,
    MistakeCategory,
    ReviewReason,
    Subject,
)

TASKS = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "тест"
  verification_status: REVIEWED
tasks:
  - {exam_item: 6, statement: "Решите 3x = 12.", answer: 4, skills: [M06.algebraic]}
  - {exam_item: 6, statement: "Решите 2x = 10.", answer: 5, skills: [M06.algebraic]}
  - {exam_item: 6, statement: "Решите 2^x = 8.", answer: 3, skills: [M06.exponential]}
  - {exam_item: 4, statement: "Вероятность орла.", answer: "0,5"}
"""


@pytest.fixture
def ids(tutor, write_file):
    tutor.import_tasks(write_file("t.yaml", TASKS))
    return {t.statement: t.id for t in tutor.tasks()}


def solve(tutor, task_id: int, answer: str):
    attempt = tutor.start_attempt(task_id)
    return tutor.submit_answer(attempt.id, answer).attempt


def test_attempts_update_mastery_and_snapshot(tutor, ids, fixed_clock):
    assert tutor.skill_masteries() == []
    solve(tutor, ids["Решите 3x = 12."], "4")
    [m] = tutor.skill_masteries(Subject.MATH_PROFILE)
    assert m.skill_code == "M06.algebraic"
    assert m.value > 0.9 and m.attempts == 1 and m.model_version == "v0"
    snaps = tutor.repository.list_snapshots("M06.algebraic")
    assert [s.snapshot_date for s in snaps] == [fixed_clock.today()]

    fixed_clock.advance(dt.timedelta(days=1))
    solve(tutor, ids["Решите 2x = 10."], "7")
    [m2] = tutor.skill_masteries()
    assert m2.value < m.value and m2.attempts == 2
    days = [s.snapshot_date for s in tutor.repository.list_snapshots("M06.algebraic")]
    assert len(days) == 2  # вчерашний снимок не переписан
    assert tutor.repository.list_snapshots("M06.algebraic")[0].value == pytest.approx(m.value)


def test_forgetting_lowers_value_over_time(tutor, ids, fixed_clock):
    solve(tutor, ids["Решите 3x = 12."], "4")
    today = tutor.skill_masteries()[0].value
    fixed_clock.advance(dt.timedelta(days=20))
    later = tutor.skill_masteries()[0]
    assert later.value < today
    assert later.review_due


def test_predictions_are_logged_and_resolved(tutor, ids):
    first = tutor.start_attempt(ids["Решите 3x = 12."])
    tutor.submit_answer(first.id, "4")
    second = tutor.start_attempt(ids["Решите 2x = 10."])
    no_skills = tutor.start_attempt(ids["Вероятность орла."])
    tutor.submit_answer(no_skills.id, "0,5")
    log = {p.attempt_id: p for p in tutor.repository.list_predictions()}
    assert log[first.id].predicted == 0.0 and log[first.id].outcome == 1  # навык не изучен
    assert log[second.id].predicted > 0.9 and log[second.id].outcome is None  # брошена
    assert no_skills.id not in log
    calibration = tutor.calibration()
    assert calibration.count == 1 and calibration.brier == pytest.approx(1.0)


def test_mistakes_are_classified_and_can_be_corrected(tutor, ids):
    wrong = solve(tutor, ids["Решите 3x = 12."], "-4")
    [m] = tutor.attempt_mistakes(wrong.id)
    assert m.category == MistakeCategory.CARELESS and m.classified_by == ClassifiedBy.RULE
    assert m.skill_code == "M06.algebraic"
    [pattern] = tutor.mistake_patterns()
    assert pattern.category == MistakeCategory.CARELESS and pattern.occurrences == 1

    fixed = tutor.reclassify_mistake(m.id, MistakeCategory.CONDITION)
    assert fixed.classified_by == ClassifiedBy.USER and fixed.confidence == 1.0
    assert [x.category for x in tutor.attempt_mistakes(wrong.id)] == [MistakeCategory.CONDITION]
    history = tutor.repository.list_mistakes(attempt_id=wrong.id, current_only=False)
    assert len(history) == 2  # исходная запись правила сохранена
    assert [p.category for p in tutor.mistake_patterns()] == [MistakeCategory.CONDITION]
    with pytest.raises(AppError, match="уже уточнена"):
        tutor.reclassify_mistake(m.id, MistakeCategory.FORMULA)

    gave_up = tutor.start_attempt(ids["Вероятность орла."])
    tutor.give_up(gave_up.id)
    [none_skill] = tutor.attempt_mistakes(gave_up.id)
    assert none_skill.skill_code is None and none_skill.category == MistakeCategory.TOPIC_GAP


def test_review_queue_and_review_attempt(tutor, ids, fixed_clock):
    with pytest.raises(AppError, match="очередь повторений пуста"):
        tutor.start_review()
    solve(tutor, ids["Решите 3x = 12."], "4")
    solve(tutor, ids["Решите 2^x = 8."], "8")  # ошибка → паттерн по M06.exponential
    queue = tutor.review_queue()
    assert queue[0].skill_code == "M06.exponential"
    assert queue[0].reason == ReviewReason.FORGETTING  # M ниже порога — повторять сразу
    assert all(i.skill_code != "M06.algebraic" for i in queue)

    fixed_clock.advance(dt.timedelta(days=30))
    codes = [i.skill_code for i in tutor.review_queue(Subject.MATH_PROFILE)]
    assert "M06.algebraic" in codes
    assert tutor.review_queue(Subject.INFORMATICS) == []

    review = tutor.start_review(Subject.MATH_PROFILE)
    assert review.mode == AttemptMode.REVIEW
    assert "M06.exponential" in tutor.task(review.task_id).skills


def test_recalculate_rebuilds_from_history(tutor, ids):
    solve(tutor, ids["Решите 3x = 12."], "4")
    solve(tutor, ids["Решите 2^x = 8."], "8")
    before = {m.skill_code: m.value for m in tutor.skill_masteries()}
    assert tutor.recalculate_mastery() == 2
    after = {m.skill_code: m.value for m in tutor.skill_masteries()}
    assert after == pytest.approx(before)


def test_aggregates_by_topic_and_exam_item(tutor, ids):
    solve(tutor, ids["Решите 3x = 12."], "4")
    items = {a.key: a for a in tutor.mastery_by_exam_item(Subject.MATH_PROFILE)}
    six = items["6"]
    assert 0 < six.value < 1  # изучен один навык из нескольких
    assert six.studied == 1 and six.total > 1
    assert items["4"].value is None
    topics = tutor.mastery_by_topic(Subject.MATH_PROFILE)
    assert any(t.value is not None for t in topics)
