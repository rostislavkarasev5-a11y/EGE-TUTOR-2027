"""ИИ-помощник (Phase 6, ADR-0017): CORE решает и записывает, ИИ только предлагает."""

import datetime as dt

import pytest

from ege_tutor.config import load_settings
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    AICallStatus,
    AIError,
    AIPurpose,
    AITaskSuggestion,
    AttemptMode,
    MistakeCategory,
    Subject,
    TaskSource,
    VerificationStatus,
)
from ege_tutor.core.services.assistant import AI_FORBIDDEN_MODES, month_start, reveals_answer
from tests.fakes import FakeAIService, LocalSandbox, ScriptedSandbox, usage

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
    statement: "Решите уравнение 2^x = 8."
    answer: 3
    solution: "8 = 2^3, x = 3."
    skills: [M06.exponential]
  - exam_item: 13
    statement: "Решите уравнение и отберите корни на отрезке."
    solution: "Эталонное решение."
"""

INFORMATICS = """
defaults:
  subject: informatics
  source: USER_MATERIAL
  source_ref: "тест"
tasks:
  - exam_item: 5
    statement: "Сколько будет 2 в степени 10?"
    answer: 1024
"""


@pytest.fixture
def fake_ai() -> FakeAIService:
    return FakeAIService()


def _make(fixed_clock, fake_ai, *, budget: float | None = None, sandbox=None) -> TutorApp:
    settings = load_settings()
    if budget is not None:
        ai = settings.app.ai.model_copy(update={"monthly_budget_rub": budget})
        settings = settings.model_copy(update={"app": settings.app.model_copy(update={"ai": ai})})
    return TutorApp.create(
        settings=settings, clock=fixed_clock, ai=fake_ai, sandbox=sandbox or LocalSandbox()
    )


@pytest.fixture
def app(fixed_clock, fake_ai):
    tutor = _make(fixed_clock, fake_ai)
    yield tutor
    tutor.close()


@pytest.fixture
def ids(app, write_file):
    app.import_tasks(write_file("t.yaml", TASKS))
    found = {t.statement: t.id for t in app.tasks()}
    ordered = [found[s] for s in sorted(found, key=found.get)]
    for task_id in ordered[:2]:
        app.review_task(task_id, answer_is_correct=True)
    return ordered


# ── без ИИ ──────────────────────────────────────────────────────────────────


def test_ai_is_off_by_default_and_app_still_works(tutor, write_file):
    status = tutor.ai_status()
    assert status.available is False
    assert status.provider == "disabled"
    assert "выключен" in (status.reason or "")
    assert tutor.info().ai_available is False
    tutor.import_tasks(write_file("t.yaml", TASKS))
    task = tutor.tasks()[1]
    tutor.review_task(task.id, answer_is_correct=True)
    attempt = tutor.start_attempt(task.id)
    assert tutor.ai_hint_level(attempt.id) is None
    with pytest.raises(AppError, match="ИИ недоступен"):
        tutor.ai_hint(attempt.id)
    assert tutor.submit_answer(attempt.id, "3").attempt.correct


# ── подсказки ───────────────────────────────────────────────────────────────


def test_ai_hint_is_recorded_like_a_hint(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    assert app.ai_hint_level(attempt.id) == 1
    hint = app.ai_hint(attempt.id)
    assert hint.level == 1
    assert hint.text == fake_ai.hint_text
    assert app.attempt(attempt.id).max_hint_level == 1
    shown = app.shown_hints(attempt.id)
    assert [(h.level, h.by_ai, h.text) for h in shown] == [(1, True, fake_ai.hint_text)]
    result = app.submit_answer(attempt.id, "3")
    assert result.attempt.correct and not result.attempt.independent
    [call] = app.ai_calls()
    assert call.purpose == AIPurpose.HINT and call.status == AICallStatus.OK
    assert call.cost_rub == pytest.approx((1000 * 1.2 + 500 * 1.2) / 1000)
    assert app.ai_status().month_spent_rub == pytest.approx(1.8)


def test_recorded_hints_come_before_ai(app, ids):
    attempt = app.start_attempt(ids[0])  # у задачи записаны подсказки 1 и 2
    assert app.ai_hint_level(attempt.id) is None
    with pytest.raises(AppError, match="записанная подсказка"):
        app.ai_hint(attempt.id)
    app.next_hint(attempt.id)
    app.next_hint(attempt.id)
    assert app.ai_hint_level(attempt.id) == 3
    assert app.ai_hint(attempt.id).level == 3
    with pytest.raises(AppError, match="уровней 1–3"):
        app.ai_hint(attempt.id)


def test_hint_revealing_answer_is_rejected(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    fake_ai.hint_text = "Ответ: 3"
    with pytest.raises(AppError, match="раскрывала ответ"):
        app.ai_hint(attempt.id)
    assert app.attempt(attempt.id).max_hint_level == 0
    assert app.shown_hints(attempt.id) == []
    [call] = app.ai_calls()
    assert call.status == AICallStatus.REJECTED
    assert call.cost_rub > 0  # отклонённый ответ всё равно стоил денег


@pytest.mark.parametrize(
    ("text", "answer", "reveals"),
    [
        ("x = 12", "12", True),
        ("подели на 120", "12", False),
        ("раздели обе части на 2", "2", False),
        ("получится ответ 2", "2", True),
        ("x = 0,5", "0.5", True),
        ("шаг 1.5 не нужен", "1", False),
        ("ничего не сказано", None, False),
    ],
)
def test_reveals_answer(text, answer, reveals):
    assert reveals_answer(text, answer) is reveals


# ── правила режимов и личные данные ─────────────────────────────────────────


def test_ai_is_forbidden_in_measuring_modes():
    assert {
        AttemptMode.DIAGNOSTIC,
        AttemptMode.CONTROL,
        AttemptMode.MOCK,
        AttemptMode.EXAM,
    } <= AI_FORBIDDEN_MODES
    assert AttemptMode.PRACTICE not in AI_FORBIDDEN_MODES


def test_diagnostic_never_reaches_ai(app, fake_ai):
    app.install_starter_bank()
    session = app.start_diagnostic(Subject.MATH_PROFILE)
    step = app.diagnostic_step(session.id)
    assert step.attempt is not None
    assert app.ai_allowed_for(step.attempt.id) is False
    assert app.ai_hint_level(step.attempt.id) is None
    with pytest.raises(AppError, match="диагностике"):
        app.ai_hint(step.attempt.id)
    app.give_up(step.attempt.id)
    with pytest.raises(AppError, match="диагностике"):
        app.ai_explain(step.attempt.id)
    assert fake_ai.calls == []


def test_personal_data_is_not_sent(app, ids, fake_ai):
    app.update_profile(display_name="Тестовый Ученик", targets={Subject.MATH_PROFILE: 95})
    attempt = app.start_attempt(ids[1])
    app.ai_hint(attempt.id)
    [(_, context)] = fake_ai.calls
    assert "Тестовый" not in repr(context)
    assert "95" not in repr(context)


# ── объяснение, ошибки ──────────────────────────────────────────────────────


def test_explanation_only_after_attempt_and_cached(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    with pytest.raises(AppError, match="после ответа"):
        app.ai_explain(attempt.id)
    app.give_up(attempt.id)
    note = app.ai_explain(attempt.id)
    assert note.text == fake_ai.explanation
    assert app.ai_explain(attempt.id).id == note.id
    assert app.ai_explanation(attempt.id) == note
    assert len(fake_ai.calls) == 1


def test_ai_error_is_recorded_and_reported(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    app.give_up(attempt.id)
    fake_ai.error = AIError("сбой связи", usage(200, 0))
    with pytest.raises(AppError, match="ИИ не помог: сбой связи"):
        app.ai_explain(attempt.id)
    [call] = app.ai_calls()
    assert call.status == AICallStatus.ERROR
    assert call.error == "сбой связи"
    assert call.cost_rub == pytest.approx(0.24)


def test_mistake_suggestion_is_only_a_suggestion(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    app.submit_answer(attempt.id, "4")
    [mistake] = app.attempt_mistakes(attempt.id)
    note = app.ai_classify_mistake(mistake.id)
    assert note.category == MistakeCategory.ARITHMETIC
    assert note.confidence == pytest.approx(0.8)
    assert app.attempt_mistakes(attempt.id)[0].category == mistake.category  # ничего не изменено
    assert app.ai_mistake_note(mistake.id) == note
    fixed = app.reclassify_mistake(mistake.id, note.category)
    assert fixed.category == MistakeCategory.ARITHMETIC


def test_unknown_mistake_category_is_rejected(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    app.submit_answer(attempt.id, "4")
    [mistake] = app.attempt_mistakes(attempt.id)
    fake_ai.category = "LAZINESS"
    with pytest.raises(AppError, match="LAZINESS"):
        app.ai_classify_mistake(mistake.id)
    assert app.ai_mistake_note(mistake.id) is None
    assert app.ai_calls()[0].status == AICallStatus.REJECTED


# ── бюджет ──────────────────────────────────────────────────────────────────


def test_monthly_budget_switches_ai_off_until_next_month(fixed_clock, fake_ai, write_file):
    app = _make(fixed_clock, fake_ai, budget=2.0)
    try:
        app.import_tasks(write_file("t.yaml", TASKS))
        task = sorted(app.tasks(), key=lambda t: t.id)[1]
        app.review_task(task.id, answer_is_correct=True)
        first = app.start_attempt(task.id)
        app.ai_hint(first.id)  # 1,8 ₽
        app.give_up(first.id)
        app.ai_explain(first.id)  # ещё 1,8 ₽ — лимит пройден
        status = app.ai_status()
        assert status.available is False
        assert "лимит" in (status.reason or "")
        second = app.start_attempt(task.id)
        with pytest.raises(AppError, match="лимит"):
            app.ai_hint(second.id)
        assert len(fake_ai.calls) == 2
        fixed_clock.advance(dt.timedelta(days=31))
        assert app.ai_status().available is True
        assert app.ai_status().month_spent_rub == 0
    finally:
        app.close()


def test_month_start_is_first_day_utc():
    moment = dt.datetime(2026, 10, 8, 1, 30, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    assert month_start(moment) == dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


# ── часть 2 ─────────────────────────────────────────────────────────────────


def test_part2_grade_is_clamped_and_stored(app, ids, fake_ai):
    from ege_tutor.core.domain import AICriterionScore

    fake_ai.criteria = (
        AICriterionScore("Верный ответ", 5, 2, "слишком щедро"),
        AICriterionScore("Отбор корней", 1, 1, "есть"),
    )
    with pytest.raises(AppError, match="короткое"):
        app.ai_grade_part2(ids[2], "x=1")
    with pytest.raises(AppError, match="развёрнутым"):
        app.ai_grade_part2(ids[1], "подробное решение задачи с объяснением")
    grade = app.ai_grade_part2(ids[2], "  Решение: замена t = sin x, получаем ... ответ.  ")
    assert grade.max_points == 2  # задание 13 оценивается в 2 балла
    assert [c.points for c in grade.criteria] == [2, 1]
    assert grade.points == 2
    assert grade.status.value == "AI_PRELIMINARY"
    assert grade.solution_text.startswith("Решение")
    assert app.part2_grades(ids[2]) == [grade]
    assert app.part2_grade(grade.id) == grade


# ── похожие задачи ──────────────────────────────────────────────────────────


def _suggestion(statement: str, answer: str, check: str) -> AITaskSuggestion:
    return AITaskSuggestion(statement, answer, "решение по шагам", check, usage())


def test_generated_math_task_is_checked_and_labelled(app, ids, fake_ai):
    fake_ai.generated = _suggestion("Решите уравнение 3^x = 81.", "4", "log(81)/log(3)")
    made = app.ai_generate_similar(ids[1])
    task = made.task
    assert task.source == TaskSource.AI_GENERATED
    assert task.verification_status == VerificationStatus.AUTO_CHECKED
    assert task.can_practice
    assert "ИИ" in task.source_ref and f"№{ids[1]}" in task.source_ref
    assert task.skills == ("M06.exponential",)
    assert task.answer == "4"
    assert made.batch.added_count == 1
    assert app.ai_calls()[0].purpose == AIPurpose.GENERATE


@pytest.mark.parametrize(
    ("answer", "check", "match"),
    [
        ("5", "2^2", "не сошёлся"),
        ("пять", "5", "на бланке"),
    ],
)
def test_wrong_generated_task_is_not_saved(app, ids, fake_ai, answer, check, match):
    before = len(app.tasks())
    fake_ai.generated = _suggestion("Решите уравнение 2^x = 16.", answer, check)
    with pytest.raises(AppError, match=match):
        app.ai_generate_similar(ids[1])
    assert len(app.tasks()) == before
    assert app.ai_calls()[0].status == AICallStatus.REJECTED


def test_duplicate_generated_task_is_rejected(app, ids, fake_ai):
    fake_ai.generated = _suggestion("Решите уравнение 2^x = 8.", "3", "3")
    with pytest.raises(AppError, match="уже есть"):
        app.ai_generate_similar(ids[1])


def test_generation_limits(app, ids):
    with pytest.raises(AppError, match="развёрнутым"):
        app.ai_generate_similar(ids[2])


def test_generated_informatics_task_is_checked_in_sandbox(app, fake_ai, write_file):
    app.import_tasks(write_file("i.yaml", INFORMATICS))
    [sample] = app.tasks(Subject.INFORMATICS)
    fake_ai.generated = _suggestion("Сколько будет 3 в степени 5?", "243", "print(3 ** 5)")
    made = app.ai_generate_similar(sample.id)
    assert made.task.verification_status == VerificationStatus.AUTO_CHECKED
    fake_ai.generated = _suggestion("Сколько будет 3 в степени 6?", "700", "print(3 ** 6)")
    with pytest.raises(AppError, match="не сошёлся"):
        app.ai_generate_similar(sample.id)


def test_generated_task_stays_unverified_without_sandbox(fixed_clock, fake_ai, write_file):
    app = _make(fixed_clock, fake_ai, sandbox=ScriptedSandbox(available=False))
    try:
        app.import_tasks(write_file("i.yaml", INFORMATICS))
        [sample] = app.tasks(Subject.INFORMATICS)
        fake_ai.generated = _suggestion("Сколько будет 5 в степени 3?", "125", "print(5 ** 3)")
        made = app.ai_generate_similar(sample.id)
        assert made.task.verification_status == VerificationStatus.UNVERIFIED
        assert not made.task.can_practice
        assert "не проверен" in made.check_note
    finally:
        app.close()
