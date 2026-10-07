"""Решение задач: выбор задачи, попытки, таймер, подсказки, самостоятельность, проверка."""

import datetime as dt

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import AttemptStatus, Verdict, VerificationStatus

TASKS = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "тест"
tasks:
  - exam_item: 6
    statement: "Решите уравнение 3x − 7 = 11."
    answer: 6
    solution: "3x = 18, x = 6."
    hints: ["Перенеси −7 вправо.", "Получится 3x = 18."]
    skills: [M06.algebraic]
  - exam_item: 6
    statement: "Решите уравнение 2x = 9."
    answer: "4,5"
    hints: {3: "Раздели обе части на 2."}
    skills: [M06.algebraic]
  - exam_item: 6
    statement: "Решите уравнение 2^x = 8."
    answer: 3
    skills: [M06.exponential]
  - exam_item: 4
    statement: "Монету бросают один раз. Найдите вероятность выпадения орла."
    answer: "0,5"
  - exam_item: 13
    statement: "Решите уравнение и отберите корни."
"""


@pytest.fixture
def ids(tutor, write_file):
    """Импортировать задачи и проверить ответы первых четырёх (пятая — часть 2)."""
    tutor.import_tasks(write_file("t.yaml", TASKS))
    tasks = {t.statement: t.id for t in tutor.tasks()}
    ordered = [tasks[s] for s in sorted(tasks, key=tasks.get)]
    for task_id in ordered[:4]:
        tutor.review_task(task_id, answer_is_correct=True)
    return ordered


def test_unverified_task_cannot_be_solved(tutor, write_file):
    tutor.import_tasks(write_file("t.yaml", TASKS))
    task = tutor.tasks()[0]
    with pytest.raises(AppError, match="ege review"):
        tutor.start_attempt(task.id)
    with pytest.raises(AppError, match="Непроверенных"):
        tutor.next_task()


def test_extended_and_disputed_tasks_are_not_given(tutor, ids):
    with pytest.raises(AppError, match="Phase 8"):
        tutor.start_attempt(ids[4])
    disputed = tutor.review_task(ids[3], answer_is_correct=False)
    assert disputed.verification_status == VerificationStatus.DISPUTED
    with pytest.raises(AppError, match="снята с выдачи"):
        tutor.start_attempt(ids[3])


def test_review_marks_task(tutor, ids, fixed_clock):
    task = tutor.task(ids[0])
    assert task.verification_status == VerificationStatus.REVIEWED
    assert task.verified_at == fixed_clock.now()
    assert tutor.next_unverified_task() is None


def test_correct_independent_attempt_with_timer(tutor, ids, fixed_clock):
    attempt = tutor.start_attempt(ids[0])
    assert attempt.attempt_no == 1
    assert attempt.time_norm_seconds == 4 * 60  # норматив задания №6 из exam_specs
    fixed_clock.advance(dt.timedelta(seconds=95))
    result = tutor.submit_answer(attempt.id, "6")
    done = result.attempt
    assert done.status == AttemptStatus.ANSWERED
    assert done.verdict == Verdict.CORRECT
    assert done.independent
    assert done.time_spent_seconds == 95
    assert done.within_norm is True


def test_slow_attempt_is_outside_norm(tutor, ids, fixed_clock):
    attempt = tutor.start_attempt(ids[0])
    fixed_clock.advance(dt.timedelta(minutes=5))
    assert tutor.submit_answer(attempt.id, "6").attempt.within_norm is False


def test_hints_go_up_skip_missing_levels_and_end_with_solution(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    levels = [tutor.next_hint(attempt.id).level for _ in range(3)]
    assert levels == [1, 2, 4]  # уровня 3 у задачи нет; 4 — полное решение
    with pytest.raises(AppError, match="решение уже показано"):
        tutor.next_hint(attempt.id)
    done = tutor.submit_answer(attempt.id, "6").attempt
    assert done.correct
    assert not done.independent
    assert done.max_hint_level == 4
    events = tutor.repository.list_hint_events(attempt.id)
    assert [e.level for e in events] == [1, 2, 4]


def test_hint_independence_comes_from_config(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    assert tutor.next_hint(attempt.id).independence == 0.75
    assert tutor.next_hint(attempt.id).independence == 0.5


def test_task_without_hints_or_solution(tutor, ids):
    attempt = tutor.start_attempt(ids[2])
    with pytest.raises(AppError, match="больше записанных подсказок нет"):
        tutor.next_hint(attempt.id)


def test_wrong_and_format_answers(tutor, ids):
    wrong = tutor.submit_answer(tutor.start_attempt(ids[1]).id, "4").attempt
    assert wrong.verdict == Verdict.WRONG
    fmt = tutor.submit_answer(tutor.start_attempt(ids[1]).id, "9/2")
    assert fmt.attempt.verdict == Verdict.WRONG_FORMAT
    assert "4,5" in fmt.check.explanation
    again = tutor.start_attempt(ids[1])
    assert again.attempt_no == 3
    assert tutor.submit_answer(again.id, "4.5").attempt.correct


def test_hints_carry_over_to_next_attempt_within_window(tutor, ids, fixed_clock):
    first = tutor.start_attempt(ids[0])
    tutor.next_hint(first.id)
    tutor.submit_answer(first.id, "5")
    second = tutor.start_attempt(ids[0])
    assert second.max_hint_level == 1
    tutor.submit_answer(second.id, "6")
    assert not tutor.attempts(ids[0], limit=1)[0].independent

    fixed_clock.advance(dt.timedelta(hours=13))
    third = tutor.start_attempt(ids[0])  # последняя попытка верная — переносить нечего
    assert third.max_hint_level == 0


def test_carryover_expires(tutor, ids, fixed_clock):
    first = tutor.start_attempt(ids[0])
    tutor.next_hint(first.id)
    tutor.give_up(first.id)
    fixed_clock.advance(dt.timedelta(hours=13))
    assert tutor.start_attempt(ids[0]).max_hint_level == 0


def test_give_up_abandon_and_history_is_kept(tutor, ids):
    a = tutor.start_attempt(ids[0])
    assert tutor.give_up(a.id).status == AttemptStatus.GAVE_UP
    b = tutor.start_attempt(ids[1])
    c = tutor.start_attempt(ids[2])  # новая попытка бросает незавершённую
    assert tutor.repository.get_attempt(b.id).status == AttemptStatus.ABANDONED
    tutor.abandon_attempt(c.id)
    with pytest.raises(AppError, match="уже завершена"):
        tutor.submit_answer(c.id, "3")
    assert len(tutor.attempts()) == 3
    assert not hasattr(tutor.repository, "delete_attempt")


def test_empty_answer_is_rejected(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    with pytest.raises(AppError, match="пустой"):
        tutor.submit_answer(attempt.id, "  ")
    assert tutor.repository.get_attempt(attempt.id).status == AttemptStatus.IN_PROGRESS


def test_next_task_prefers_least_practiced(tutor, ids):
    first = tutor.next_task(exam_item=6)
    tutor.submit_answer(tutor.start_attempt(first.id).id, "0")
    second = tutor.next_task(exam_item=6)
    assert second.id != first.id


def test_next_task_skips_unpracticable(tutor, ids):
    with pytest.raises(AppError, match="Phase 8"):
        tutor.next_task(exam_item=13)


def test_similar_task_prefers_shared_skill(tutor, ids):
    similar = tutor.similar_task(ids[0])
    assert similar.id == ids[1]  # общий навык M06.algebraic
    assert tutor.similar_task(ids[3]) is None  # других задач №4 нет


def test_import_validates_hints(tutor, write_file):
    text = """
tasks:
  - {subject: math, exam_item: 6, statement: "A", answer: 6, source: USER_MATERIAL,
     source_ref: r, hints: {4: "решение"}}
  - {subject: math, exam_item: 6, statement: "B", answer: 6, source: USER_MATERIAL,
     source_ref: r, hints: ["ответ 6"]}
  - {subject: math, exam_item: 6, statement: "C", answer: 6, source: USER_MATERIAL,
     source_ref: r, hints: ["", "x"]}
"""
    report = tutor.preview_import(write_file("h.yaml", text))
    errors = {e.row: e.message for e in report.errors}
    assert "уровни подсказок" in errors[1]
    assert 2 not in errors
    assert any(w.row == 2 and "содержит ответ" in w.message for w in report.warnings)
    assert "пустая подсказка" in errors[3]
