"""Адаптивная диагностика вместе с попытками и mastery (Phase 5, ADR-0016)."""

import datetime as dt

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import (
    AttemptMode,
    AttemptStatus,
    DiagnosticStatus,
    ItemBasis,
    StopReason,
    Subject,
)

TASKS = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "тест диагностики"
  verification_status: REVIEWED
tasks:
  - {exam_item: 1, statement: "Угол, лёгкая.", answer: 30, difficulty: 2, skills: [M01.triangles]}
  - {exam_item: 1, statement: "Угол, средняя.", answer: 40, difficulty: 3, skills: [M01.triangles]}
  - {exam_item: 1, statement: "Угол, сложная.", answer: 50, difficulty: 4, skills: [M01.triangles]}
  - {exam_item: 2, statement: "Вектор.", answer: 5, difficulty: 3, skills: [M02.coordinates]}
  - {exam_item: 13, statement: "Уравнение: сколько корней на отрезке?", answer: "2; 5",
     difficulty: 3, skills: [M13.root_selection], solution: "Полное решение."}
  - {exam_item: 3, statement: "Не проверена.", answer: 7, difficulty: 3,
     verification_status: UNVERIFIED, skills: [M03.polyhedra]}
"""


@pytest.fixture
def ids(tutor, write_file):
    tutor.import_tasks(write_file("t.yaml", TASKS))
    return {t.statement: t.id for t in tutor.tasks(limit=100)}


def answer_of(tutor, task_id: int) -> str:
    return tutor.task(task_id).answer


def test_diagnostic_runs_to_the_end_and_saves_baseline(tutor, ids, fixed_clock):
    assert tutor.diagnostic_task_count(Subject.MATH_PROFILE) == 5  # без непроверенной
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    assert session.status == DiagnosticStatus.ACTIVE
    seen = []
    while True:
        step = tutor.diagnostic_step(session.id)
        if step.attempt is None:
            break
        assert step.attempt.mode == AttemptMode.DIAGNOSTIC
        seen.append(step.task.id)
        fixed_clock.advance(dt.timedelta(minutes=2))
        tutor.submit_answer(step.attempt.id, answer_of(tutor, step.task.id))
    assert len(seen) == len(set(seen)) == 5  # каждая задача — один раз
    assert ids["Не проверена."] not in seen
    # первая задача по номеру 1 — средней сложности
    first_item1 = next(t for t in seen if tutor.task(t).exam_item == 1)
    assert first_item1 == ids["Угол, средняя."]

    done = tutor.diagnostic_session(session.id)
    assert done.status == DiagnosticStatus.FINISHED
    assert done.stop_reason == StopReason.NO_TASKS
    assert done.forecast is not None and done.forecast.max_points == 32
    results = {r.exam_item: r for r in tutor.diagnostic_results(session.id)}
    assert len(results) == 19
    assert results[1].basis == ItemBasis.DIRECT and results[1].answered == 3
    assert results[13].basis == ItemBasis.DIRECT
    assert results[3].basis == ItemBasis.NOT_ASSESSED  # есть только непроверенная
    assert results[1].probability > results[3].probability
    # попытки диагностики идут в mastery
    assert {m.skill_code for m in tutor.skill_masteries()} >= {"M01.triangles", "M02.coordinates"}
    with pytest.raises(AppError):
        tutor.finish_diagnostic(session.id)


def test_part_two_is_checked_by_final_answer_only(tutor, ids):
    task_id = ids["Уравнение: сколько корней на отрезке?"]
    with pytest.raises(AppError, match="развёрнутым"):
        tutor.start_attempt(task_id)  # в тренировке часть 2 — с Phase 8
    attempt = tutor.start_attempt(task_id, AttemptMode.DIAGNOSTIC)
    result = tutor.submit_answer(attempt.id, "2 ;5")
    assert result.check.correct


def test_no_hints_in_diagnostic(tutor, ids):
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    step = tutor.diagnostic_step(session.id)
    with pytest.raises(AppError, match="подсказок нет"):
        tutor.next_hint(step.attempt.id)
    assert tutor.attempt(step.attempt.id).max_hint_level == 0


def test_diagnostic_can_be_paused_and_resumed(tutor, ids):
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    step = tutor.diagnostic_step(session.id)
    # «закрыл вкладку» и вернулся: та же сессия и та же задача
    assert tutor.start_diagnostic(Subject.MATH_PROFILE).id == session.id
    again = tutor.diagnostic_step(session.id)
    assert again.attempt.id == step.attempt.id
    tutor.give_up(step.attempt.id)
    state = tutor.diagnostic_state(session.id)
    assert state.tasks_done == 1
    item = next(e for e in state.estimates if e.exam_item == step.task.exam_item)
    assert item.basis == ItemBasis.DIRECT
    others = [e for e in state.estimates if e.exam_item == 2 and e.exam_item != item.exam_item]
    assert all(e.basis == ItemBasis.INFERRED for e in others)


def test_finish_early_keeps_what_was_solved(tutor, ids):
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    first = tutor.diagnostic_step(session.id)
    tutor.submit_answer(first.attempt.id, answer_of(tutor, first.task.id))
    second = tutor.diagnostic_step(session.id)
    done = tutor.finish_diagnostic(session.id)
    assert done.stop_reason == StopReason.USER
    assert tutor.attempt(second.attempt.id).status == AttemptStatus.ABANDONED
    answered = [r for r in tutor.diagnostic_results(session.id) if r.answered]
    assert len(answered) == 1
    # следующая диагностика — новая сессия
    assert tutor.start_diagnostic(Subject.MATH_PROFILE).id != session.id
    assert tutor.diagnostics.baseline(Subject.MATH_PROFILE).id == session.id


def _budget(tutor, **changes):
    config = tutor.diagnostics.config
    budget = config.budget.model_copy(update=changes)
    tutor.diagnostics.config = config.model_copy(update={"budget": budget})


def test_task_budget_stops_diagnostic(tutor, ids):
    _budget(tutor, max_tasks_per_subject=2)
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    for _ in range(2):
        step = tutor.diagnostic_step(session.id)
        tutor.submit_answer(step.attempt.id, "0")
    final = tutor.diagnostic_step(session.id)
    assert final.attempt is None
    assert final.session.stop_reason == StopReason.TASK_BUDGET


def test_time_budget_stops_diagnostic(tutor, ids, fixed_clock):
    _budget(tutor, max_minutes_per_subject=10)
    session = tutor.start_diagnostic(Subject.MATH_PROFILE)
    step = tutor.diagnostic_step(session.id)
    fixed_clock.advance(dt.timedelta(minutes=11))
    tutor.submit_answer(step.attempt.id, answer_of(tutor, step.task.id))
    assert tutor.diagnostic_step(session.id).session.stop_reason == StopReason.TIME_BUDGET


def test_no_tasks_means_no_diagnostic(tutor):
    with pytest.raises(AppError, match="нет проверенных задач"):
        tutor.start_diagnostic(Subject.INFORMATICS)
