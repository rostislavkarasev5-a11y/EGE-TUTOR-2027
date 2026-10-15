"""Самопроверка части 2 (Phase 8, ADR-0022, п. 5): критерии, балл, min с оценкой ИИ, mastery."""

import pytest
from sqlalchemy import text

from ege_tutor.config import load_settings
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    AttemptMode,
    AttemptStatus,
    LessonStep,
    Part2GradeStatus,
    Subject,
    Verdict,
)
from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.core.services.criteria import CRITERIA_DIR, CriteriaError, load_criteria
from tests.fakes import FakeAIService, LocalSandbox

TASKS = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "тест самопроверки"
  verification_status: REVIEWED
tasks:
  - exam_item: 14
    statement: "Решите уравнение и отберите корни на отрезке."
    solution: "Эталонное решение: замена, серии корней, отбор на окружности."
    hints: ["Сделай замену t = sin x."]
    skills: [M13.root_selection]
  - exam_item: 14
    statement: "Уравнение без эталонного решения."
    answer: "3"
    skills: [M13.root_selection]
  - exam_item: 7
    statement: "Решите уравнение 3x − 7 = 11."
    answer: 6
    skills: [M06.algebraic]
"""

CRITERIA = """
subject: MATH_PROFILE
source: AI_GENERATED
note: "Пересказ критериев своими словами"
items:
  - number: 14
    max_points: 2
    levels:
      - {points: 2, text: "Оба пункта верно"}
      - {points: 1, text: "Только пункт а"}
      - {points: 0, text: "Ничего из выше"}
    tips: ["Смотри на отбор корней"]
"""


@pytest.fixture
def ids(tutor, write_file):
    tutor.import_tasks(write_file("t.yaml", TASKS))
    by_statement = {t.statement: t.id for t in tutor.tasks(limit=100)}
    return [by_statement[s] for s in sorted(by_statement, key=by_statement.get)]


@pytest.fixture
def fake_ai() -> FakeAIService:
    return FakeAIService()


@pytest.fixture
def ai_app(fixed_clock, fake_ai, write_file):
    app = TutorApp.create(clock=fixed_clock, ai=fake_ai, sandbox=LocalSandbox())
    app.import_tasks(write_file("t.yaml", TASKS))
    yield app
    app.close()


# ── критерии ────────────────────────────────────────────────────────────────


def _content(tmp_path, criteria: str | None):
    """Папка content/ с настоящим каталогом и своим файлом критериев."""
    content = load_settings().content_dir
    folder = tmp_path / "content"
    if criteria is not None:
        (folder / CRITERIA_DIR).mkdir(parents=True)
        (folder / CRITERIA_DIR / "math_profile.yaml").write_text(criteria, encoding="utf-8")
    return content, folder


def test_loader_accepts_valid_file_and_real_content(tmp_path):
    content, folder = _content(tmp_path, CRITERIA)
    catalog = load_catalog(content)
    library = load_criteria(folder, catalog)
    found = library.get(Subject.MATH_PROFILE, 14)
    assert [lv.points for lv in found.levels] == [2, 1, 0]
    assert found.tips == ("Смотри на отбор корней",)
    assert not found.generic
    # без файла — общий список уровней, для краткого ответа — None
    fallback = library.get(Subject.MATH_PROFILE, 19)
    assert fallback.generic and fallback.max_points == 4
    assert fallback.levels[0].text == "4 из 4 баллов"
    assert library.get(Subject.MATH_PROFILE, 7) is None
    assert library.get(Subject.INFORMATICS, 27) is None
    # настоящий файл репозитория проходит те же проверки
    assert len(load_criteria(content, catalog)) >= 1


def test_loader_without_directory_uses_generic_levels(tmp_path):
    content, folder = _content(tmp_path, None)
    library = load_criteria(folder, load_catalog(content))
    assert len(library) == 0
    assert library.get(Subject.MATH_PROFILE, 14).generic


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("number: 14", "number: 7"), "не задание с развёрнутым"),
        (("max_points: 2", "max_points: 3"), "max_points"),
        (("{points: 1, text", "{points: 2, text"), "ровно один раз"),
        (('{points: 0, text: "Ничего из выше"}', '{points: 0, text: ""}'), "непустой текст"),
        (("subject: MATH_PROFILE", "subject: CHEMISTRY"), "неизвестный предмет"),
    ],
)
def test_loader_rejects_bad_criteria(tmp_path, change, message):
    content, folder = _content(tmp_path, CRITERIA.replace(*change))
    with pytest.raises(CriteriaError, match=message):
        load_criteria(folder, load_catalog(content))


def test_part2_criteria_for_task(tutor, ids):
    criteria = tutor.part2_criteria(ids[0])
    assert criteria.max_points == 2 and criteria.levels[0].points == 2
    with pytest.raises(AppError, match="краткий ответ"):
        tutor.part2_criteria(ids[2])


# ── когда часть 2 можно решать ──────────────────────────────────────────────


def test_extended_task_needs_solution_and_self_check_mode(tutor, ids):
    task = tutor.task(ids[0])
    assert task.can_practice and task.self_checkable and not task.auto_checkable
    for mode in (AttemptMode.PRACTICE, AttemptMode.HOMEWORK, AttemptMode.REVIEW):
        assert tutor.practice.why_not_practicable(task, mode) is None
    for mode in (AttemptMode.CONTROL, AttemptMode.MOCK, AttemptMode.EXAM):
        assert "самопроверкой" in tutor.practice.why_not_practicable(task, mode)
    with pytest.raises(AppError, match="нет эталонного решения"):
        tutor.start_attempt(ids[1])
    # в контрольной части 2 нет, поэтому она и не открывается
    assert "развёрнутым" in tutor.control_unavailable(Subject.MATH_PROFILE, 14)
    assert tutor.next_task(exam_item=14).id == ids[0]


def test_submit_is_refused_for_self_check(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    with pytest.raises(AppError, match="самопроверкой"):
        tutor.submit_answer(attempt.id, "5")
    assert tutor.is_self_check(attempt.id)


# ── самооценка ──────────────────────────────────────────────────────────────


def test_self_grade_partial_points(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    check = tutor.self_check(attempt.id)
    assert check.task.solution and check.ai_grades == ()
    assert tutor.attempt(attempt.id).max_hint_level == 0  # эталон — не подсказка
    for bad in (-1, 3):
        with pytest.raises(AppError, match="от 0 до 2"):
            tutor.self_grade(attempt.id, bad)
    result = tutor.self_grade(attempt.id, 1)
    done = result.attempt
    assert done.status == AttemptStatus.ANSWERED
    assert done.verdict == Verdict.WRONG
    assert (done.points, done.max_points) == (1, 2)
    assert done.answer == "самопроверка: 1 из 2"
    assert done.max_hint_level == 0
    grades = tutor.attempt_part2_grades(attempt.id)
    assert [g.status for g in grades] == [Part2GradeStatus.SELF]
    assert grades[0].points == 1
    assert grades[0].summary == tutor.part2_criteria(ids[0]).level(1).text
    # обычный путь завершения: ошибка записана, mastery посчитано по доле балла
    assert tutor.attempt_mistakes(attempt.id)
    mastery = {m.skill_code: m for m in tutor.skill_masteries()}
    assert 0 < mastery["M13.root_selection"].value < 1
    # попытка остаётся в истории, повторно оценить нельзя
    with pytest.raises(AppError, match="завершена"):
        tutor.self_grade(attempt.id, 2)
    assert tutor.attempts(ids[0])[0].points == 1


def test_full_points_is_correct_and_independent(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    done = tutor.self_grade(attempt.id, 2).attempt
    assert done.verdict == Verdict.CORRECT and done.independent
    assert not tutor.attempt_mistakes(attempt.id)


def test_hint_before_self_check_is_counted(tutor, ids):
    attempt = tutor.start_attempt(ids[0])
    tutor.next_hint(attempt.id)
    done = tutor.self_grade(attempt.id, 2).attempt
    assert done.correct and not done.independent and done.max_hint_level == 1


def test_ai_grade_attached_to_attempt_and_min_counts(ai_app, fake_ai):
    from ege_tutor.core.domain import AICriterionScore

    task_id = ai_app.next_task(exam_item=14).id
    other = ai_app.start_attempt(ai_app.next_task(exam_item=7).id)
    ai_app.give_up(other.id)
    with pytest.raises(AppError, match="другую задачу"):
        ai_app.ai_grade_part2(task_id, "Подробное решение с отбором корней.", other.id)
    attempt = ai_app.start_attempt(task_id)
    fake_ai.criteria = (AICriterionScore("Пункт а", 1, 2, "только а"),)
    grade = ai_app.ai_grade_part2(task_id, "Подробное решение с отбором корней.", attempt.id)
    assert grade.attempt_id == attempt.id and grade.points == 1
    assert ai_app.self_check(attempt.id).ai_grades == (grade,)
    result = ai_app.self_grade(attempt.id, 2)
    assert result.attempt.points == 1  # в mastery идёт меньшая
    assert result.attempt.verdict == Verdict.WRONG
    assert "меньшая" in result.check.explanation
    statuses = {g.status: g.points for g in ai_app.attempt_part2_grades(attempt.id)}
    assert statuses == {Part2GradeStatus.SELF: 2, Part2GradeStatus.AI_PRELIMINARY: 1}
    with pytest.raises(AppError, match="до самопроверки"):
        ai_app.ai_grade_part2(task_id, "Подробное решение с отбором корней.", attempt.id)


def test_lesson_counts_self_checked_attempts(tutor):
    tutor.install_starter_bank()
    tutor.learning.config = tutor.learning.config.model_copy(update={"independent_tasks": 2})
    lesson = tutor.start_lesson("M13.root_selection")
    tutor.confirm_lesson_step(lesson.id)
    tutor.confirm_lesson_step(lesson.id)
    first = tutor.lesson_attempt(lesson.id)
    assert tutor.is_self_check(first.id)
    tutor.self_grade(first.id, 2)
    second = tutor.lesson_attempt(lesson.id)
    tutor.self_grade(second.id, 1)
    assert tutor.lesson(lesson.id).step == LessonStep.CHECK
    check = tutor.lesson_check(lesson.id)
    assert (check.total, check.good) == (2, 1)
    assert check.problems == (second.id,)  # неполный балл — ошибка для разбора


def test_migration_0011_up_and_down(tmp_path):
    from alembic import command

    from ege_tutor.db.engine import alembic_config, make_engine, upgrade_to_head

    engine = make_engine(tmp_path / "m.db")
    upgrade_to_head(engine)
    config = alembic_config(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO subject (code) VALUES ('MATH_PROFILE')"))
        conn.execute(
            text(
                "INSERT INTO task (id, subject, exam_item, statement, answer_type, source, "
                "source_ref, verification_status, content_hash, is_active, created_at) VALUES "
                "(1, 'MATH_PROFILE', 14, 'x', 'EXTENDED', 'USER_MATERIAL', 'т', 'REVIEWED', 'h', "
                "1, '2026-10-01 10:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO attempt (id, task_id, mode, attempt_no, status, started_at, "
                "max_hint_level, points, max_points) VALUES (1, 1, 'PRACTICE', 1, 'ANSWERED', "
                "'2026-10-01 10:00:00', 0, 1, 2)"
            )
        )
        for status in ("SELF", "AI_PRELIMINARY"):
            conn.execute(
                text(
                    "INSERT INTO part2_grade (task_id, attempt_id, solution_text, points, "
                    "max_points, criteria_json, summary, status, created_at) VALUES "
                    "(1, 1, '', 1, 2, '[]', 's', :status, '2026-10-01 10:00:00')"
                ),
                {"status": status},
            )
    command.downgrade(config, "0010")
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(attempt)"))}
        statuses = conn.execute(text("SELECT status FROM part2_grade")).scalars().all()
        attempts = conn.execute(text("SELECT count(*) FROM attempt")).scalar()
    assert "points" not in columns and "max_points" not in columns
    assert statuses == ["AI_PRELIMINARY"]
    assert attempts == 1  # попытки не удаляются
    upgrade_to_head(engine)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(attempt)"))}
    assert {"points", "max_points"} <= columns
    engine.dispose()
