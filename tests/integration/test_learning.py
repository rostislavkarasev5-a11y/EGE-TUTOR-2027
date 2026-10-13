"""Phase 8 (ADR-0022): учебный блок по навыку, домашка в плане, теория из content/theory/."""

import datetime as dt

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import (
    AttemptMode,
    LessonStatus,
    LessonStep,
    LessonTaskRole,
    PlanItemKind,
    Subject,
)
from ege_tutor.core.services.theory import TheoryError, load_theory, parse_theory

SKILL = "M04.classical"  # в стартовом банке 3 задачи на этот навык
THEORY_FILE = """---
skill: M04.classical
title: Классическая вероятность
source: AI_GENERATED
version: 1
examples:
  - title: Монета
    statement: Монету бросают один раз. Найдите вероятность орла.
    solution: Исходов два, благоприятный один.
    answer: "0.5"
    check: "1/2"
---
Вероятность = благоприятные / все исходы.
"""


@pytest.fixture
def banked(tutor):
    tutor.install_starter_bank()
    return tutor


def _small(tutor, **changes):
    """Меньше задач на шаг: в стартовом банке по 3 задачи на навык."""
    tutor.learning.config = tutor.learning.config.model_copy(
        update={"independent_tasks": 3, "homework_base": 2, **changes}
    )


def _solve(tutor, attempt, correct=True):
    task = tutor.task(attempt.task_id)
    tutor.submit_answer(attempt.id, task.answer if correct else "123456789")


def _do_step(tutor, lesson_id, correct=True):
    """Решить все задачи текущего шага (до смены шага)."""
    step = tutor.lesson(lesson_id).step
    solved = 0
    while tutor.lesson(lesson_id).step == step:
        attempt = tutor.lesson_attempt(lesson_id)
        if attempt is None:
            break
        _solve(tutor, attempt, correct)
        solved += 1
    return solved


def test_lesson_without_mistakes_skips_review(banked):
    tutor = banked
    _small(tutor)
    lesson = tutor.start_lesson(SKILL)
    assert lesson.step == LessonStep.THEORY
    assert tutor.start_lesson(SKILL).id == lesson.id  # повторный старт — тот же блок
    assert tutor.lesson_attempt(lesson.id) is None  # на теории задач нет
    with pytest.raises(AppError, match="разбор ошибок"):
        tutor.mark_lesson_mistake_reviewed(lesson.id, 1)
    assert tutor.confirm_lesson_step(lesson.id).step == LessonStep.EXAMPLES
    assert tutor.confirm_lesson_step(lesson.id).step == LessonStep.INDEPENDENT

    attempt = tutor.lesson_attempt(lesson.id)
    assert attempt.mode == AttemptMode.PRACTICE
    assert tutor.lesson_attempt(lesson.id).id == attempt.id  # открытая попытка та же
    assert _do_step(tutor, lesson.id) == 3
    assert tutor.lesson(lesson.id).step == LessonStep.CHECK
    check = tutor.lesson_check(lesson.id)
    assert check.total == 3 and check.good == 3 and check.passed and not check.problems

    homework = tutor.confirm_lesson_step(lesson.id)
    assert homework.step == LessonStep.HOMEWORK and homework.mistake_skills == ()
    assert homework.homework_due == tutor.today() + dt.timedelta(days=1)
    tomorrow = tutor.daily_plan(homework.homework_due)
    item = next(i for i in tomorrow.items if i.kind == PlanItemKind.HOMEWORK)
    assert item.mandatory and item.tasks == 2 and item.skill_code == SKILL

    first = tutor.lesson_attempt(lesson.id)
    assert first.mode == AttemptMode.HOMEWORK
    _do_step(tutor, lesson.id)
    done = tutor.lesson(lesson.id)
    assert done.status == LessonStatus.DONE and done.step == LessonStep.DONE
    roles = [t.role for t in tutor.lesson_tasks(lesson.id)]
    assert roles.count(LessonTaskRole.INDEPENDENT) == 3
    assert roles.count(LessonTaskRole.HOMEWORK) == 2


def test_lesson_with_mistakes_goes_through_review(banked):
    tutor = banked
    _small(tutor)
    lesson = tutor.start_lesson(SKILL)
    tutor.confirm_lesson_step(lesson.id)
    tutor.confirm_lesson_step(lesson.id)
    _solve(tutor, tutor.lesson_attempt(lesson.id), correct=False)
    hinted = tutor.lesson_attempt(lesson.id)
    tutor.give_up(hinted.id)
    _do_step(tutor, lesson.id)
    check = tutor.lesson_check(lesson.id)
    assert check.good == 1 and len(check.problems) == 2 and not check.passed

    review = tutor.confirm_lesson_step(lesson.id)
    assert review.step == LessonStep.MISTAKE_REVIEW
    assert review.mistake_skills[0] == SKILL
    assert tutor.lesson_attempt(lesson.id) is None  # на разборе задач нет
    with pytest.raises(AppError, match="не из ошибок"):
        tutor.mark_lesson_mistake_reviewed(lesson.id, 999_999)
    tutor.mark_lesson_mistake_reviewed(lesson.id, check.problems[0])
    assert tutor.lesson(lesson.id).step == LessonStep.MISTAKE_REVIEW
    after = tutor.mark_lesson_mistake_reviewed(lesson.id, check.problems[1])
    assert after.step == LessonStep.MISTAKE_TASKS

    progress = tutor.lesson_progress(lesson.id)
    assert progress.target == 2 * len(after.mistake_skills)
    _do_step(tutor, lesson.id)
    homework = tutor.lesson(lesson.id)
    assert homework.step == LessonStep.HOMEWORK
    expected = min(15, 2 + 2 * len(homework.mistake_skills))
    assert tutor.learning.target(homework, LessonTaskRole.HOMEWORK) == expected


def test_lesson_target_rules_from_config(banked):
    """Числа владельца (ADR-0022): 7 примеров, 10 самостоятельных, домашка 8 + 2 × ошибки ≤ 15."""
    tutor = banked
    cfg = tutor.learning.config
    assert (cfg.examples, cfg.independent_tasks, cfg.homework_max) == (7, 10, 15)
    lesson = tutor.start_lesson(SKILL)
    assert tutor.learning.target(lesson, LessonTaskRole.INDEPENDENT) == 10
    many = lesson.__class__(**{**lesson.__dict__, "mistake_skills": tuple("abcdefgh")})
    assert tutor.learning.target(many, LessonTaskRole.HOMEWORK) == 15
    assert tutor.learning.target(lesson, LessonTaskRole.HOMEWORK) == 8


def test_short_bank_ends_step_honestly(banked):
    tutor = banked
    lesson = tutor.start_lesson(SKILL)
    tutor.confirm_lesson_step(lesson.id)
    tutor.confirm_lesson_step(lesson.id)
    progress = tutor.lesson_progress(lesson.id)
    assert progress.target == 10 and progress.short  # в банке меньше 10 задач
    _do_step(tutor, lesson.id)
    assert tutor.lesson(lesson.id).step == LessonStep.CHECK


def test_abandon_keeps_attempts(banked):
    tutor = banked
    lesson = tutor.start_lesson(SKILL)
    tutor.confirm_lesson_step(lesson.id)
    tutor.confirm_lesson_step(lesson.id)
    attempt = tutor.lesson_attempt(lesson.id)
    abandoned = tutor.abandon_lesson(lesson.id)
    assert abandoned.status == LessonStatus.ABANDONED
    assert tutor.attempt(attempt.id).status.value == "ABANDONED"
    with pytest.raises(AppError, match="брошен"):
        tutor.confirm_lesson_step(lesson.id)
    assert tutor.start_lesson(SKILL).id != lesson.id  # можно начать заново


def test_plan_suggests_lesson_and_counts_practice(banked):
    tutor = banked
    for subject in Subject:
        tutor.finish_diagnostic(tutor.start_diagnostic(subject).id)
    tutor.save_checkin(1, available_minutes=180)
    plan = tutor.rebuild_plan()
    lessons = [i for i in plan.items if i.kind == PlanItemKind.LESSON]
    assert len(lessons) == 1 and lessons[0].skill_code and "тема" in lessons[0].reason
    with pytest.raises(AppError, match="своей странице"):
        tutor.start_plan_item(lessons[0].id)


def test_theory_loader(tmp_path, tutor):
    codes = {s.code for t in tutor.catalog.topics for s in t.skills}
    theory = parse_theory(THEORY_FILE, codes)
    assert theory.skill_code == SKILL and theory.examples[0].answer == "0.5"
    with pytest.raises(ValueError, match="source"):
        parse_theory(THEORY_FILE.replace("AI_GENERATED", "FIPI"), codes)
    with pytest.raises(ValueError, match="навыка"):
        parse_theory(THEORY_FILE.replace("M04.classical", "X.y"), codes)
    folder = tmp_path / "content" / "theory"
    folder.mkdir(parents=True)
    (folder / "wrong-name.md").write_text(THEORY_FILE, encoding="utf-8")
    with pytest.raises(TheoryError, match="имя файла"):
        load_theory(tmp_path / "content", tutor.catalog)
    (folder / "wrong-name.md").rename(folder / f"{SKILL}.md")
    assert SKILL in load_theory(tmp_path / "content", tutor.catalog)
