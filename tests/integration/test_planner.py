"""Phase 7 (ADR-0019): бюджет дня, план, 80/20, объективные причины, дисциплина, контрольная."""

import datetime as dt

import pytest

from ege_tutor.core.app import AppError
from ege_tutor.core.domain import (
    AttemptMode,
    ControlStatus,
    DisciplineColor,
    EventKind,
    PlanItemKind,
    PlanItemStatus,
    Subject,
)
from ege_tutor.core.services.planner import parse_time

MATH = Subject.MATH_PROFILE
INF = Subject.INFORMATICS
# fixed_clock: 2026-10-07 09:00 UTC = 12:00 по Москве, среда.
WED = 2


@pytest.fixture
def banked(tutor):
    """Стартовый банк загружен, диагностика по обоим предметам пройдена."""
    tutor.install_starter_bank()
    for subject in Subject:
        tutor.finish_diagnostic(tutor.start_diagnostic(subject).id)
    return tutor


def _local(tutor, hours: int, minutes: int = 0) -> dt.datetime:
    return dt.datetime.combine(tutor.today(), dt.time(hours, minutes))


def _solve(tutor, attempt, correct: bool = True) -> None:
    task = tutor.task(attempt.task_id)
    tutor.submit_answer(attempt.id, task.answer if correct else "123456789")


def test_day_follows_student_time_zone(tutor, fixed_clock):
    fixed_clock.advance(dt.timedelta(hours=13))  # 22:00 UTC = 01:00 следующего дня в Москве
    assert tutor.today() == dt.date(2026, 10, 8)
    tutor.update_profile(utc_offset_hours=-5)
    assert tutor.today() == dt.date(2026, 10, 7)
    with pytest.raises(AppError):
        tutor.update_profile(utc_offset_hours=20)


def test_budget_from_windows_events_and_checkin(tutor):
    budget = tutor.day_budget()
    assert budget.template_empty and budget.minutes == 60
    tutor.add_calendar_window(WED, parse_time("16:00"), parse_time("18:00"))
    assert tutor.day_budget().minutes == 120
    with pytest.raises(AppError, match="пересекается"):
        tutor.add_calendar_window(WED, parse_time("17:00"), parse_time("19:00"))
    tutor.add_calendar_event(
        EventKind.TRAINING, "бассейн", _local(tutor, 17), _local(tutor, 17, 30), True
    )
    tutor.add_calendar_event(EventKind.OTHER, "звонок", _local(tutor, 16), _local(tutor, 17), False)
    budget = tutor.day_budget()
    assert budget.minutes == 90 and budget.blocked_minutes == 30
    assert any("бассейн" in line for line in budget.lines)
    tutor.save_checkin(4)
    assert tutor.day_budget().minutes == 67  # 90 × 0.75
    tutor.save_checkin(4, available_minutes=30)
    assert tutor.day_budget().minutes == 22
    tutor.save_checkin(5, available_minutes=20)
    assert tutor.day_budget().day_off  # 10 мин меньше минимума — выходной


def test_first_plan_starts_with_diagnostics(tutor):
    tutor.install_starter_bank()
    plan = tutor.daily_plan()
    kinds = [i.kind for i in plan.items]
    assert kinds[0] == PlanItemKind.DIAGNOSTIC
    assert plan.items[0].mandatory
    assert all(i.reason for i in plan.items)
    with pytest.raises(AppError, match="своей странице"):
        tutor.start_plan_item(plan.items[0].id)


def test_plan_is_built_once_and_counts_attempts(banked):
    tutor = banked
    plan = tutor.daily_plan()
    assert plan.budget_minutes == 60
    assert sum(i.minutes for i in plan.items) <= 60
    assert tutor.daily_plan().items == plan.items  # второй раз не перестраивается
    assert plan.mandatory_minutes <= 60 * 0.8 or plan.mandatory_count == 1
    item = next(i for i in plan.items if i.kind == PlanItemKind.PRACTICE)
    attempt = tutor.start_plan_item(item.id)
    assert attempt.exam_item == item.exam_item and attempt.mode == AttemptMode.PRACTICE
    _solve(tutor, attempt, correct=False)  # выполнение не зависит от правильности
    progressed = next(i for i in tutor.daily_plan().items if i.id == item.id)
    assert progressed.done_tasks == 1
    assert progressed.status in (PlanItemStatus.PARTIAL, PlanItemStatus.DONE)


def test_rule_80_20(banked):
    tutor = banked
    plan = tutor.daily_plan()
    mandatory = next(i for i in plan.items if i.mandatory)
    with pytest.raises(AppError, match="обязательный"):
        tutor.remove_plan_item(mandatory.id)
    with pytest.raises(AppError, match="причину"):
        tutor.move_plan_item(mandatory.id, tutor.today() + dt.timedelta(days=1))
    moved = tutor.move_plan_item(mandatory.id, tutor.today() + dt.timedelta(days=1), "кружок")
    assert moved.mandatory and moved.carried_from == tutor.today()
    # Свои пункты — не больше 20% бюджета (12 мин из 60).
    with pytest.raises(AppError, match="80/20"):
        tutor.add_plan_item(INF, 27, 1)  # одна задача №27 дольше 12 минут
    added = tutor.add_plan_item(MATH, 1, 1)
    assert added.added_by_user and not added.mandatory
    used, limit = tutor.plan_change_limit(tutor.daily_plan())
    assert used == added.minutes and limit == 12
    tutor.remove_plan_item(added.id)
    statuses = {i.id: i.status for i in tutor.daily_plan().items}
    assert statuses[mandatory.id] == PlanItemStatus.MOVED
    assert statuses[added.id] == PlanItemStatus.REMOVED


def test_excuse_carries_mandatory_and_skips_discipline(banked, fixed_clock):
    tutor = banked
    plan = tutor.daily_plan()
    assert tutor.excuse_day("температура") == sum(1 for i in plan.items if i.open)
    tomorrow = tutor.today() + dt.timedelta(days=1)
    fixed_clock.advance(dt.timedelta(days=1))
    carried = [i for i in tutor.daily_plan().items if i.carried_from is not None]
    assert carried and all(i.mandatory for i in carried)
    assert all(i.day == tomorrow for i in carried)
    report = tutor.discipline()
    assert report.color is None  # день с причиной не учитывается
    assert report.excuse_days == 1


def test_discipline_colors_and_red_streak(banked, fixed_clock):
    tutor = banked
    for _ in range(3):  # три дня с планом, ничего не решено
        tutor.daily_plan()
        fixed_clock.advance(dt.timedelta(days=1))
    report = tutor.discipline()
    assert report.color == DisciplineColor.RED
    assert report.missed_streak == 3 and "подряд" in report.message
    # Сегодня выполнено всё обязательное → история прошлых дней не меняется.
    plan = tutor.daily_plan()
    for item in plan.items:
        if item.mandatory and item.kind == PlanItemKind.PRACTICE:
            for _ in range(item.tasks):
                _solve(tutor, tutor.start_plan_item(item.id))
    fixed_clock.advance(dt.timedelta(days=1))
    report = tutor.discipline()
    assert report.days_counted == 4 and report.missed_streak == 0
    assert report.color == DisciplineColor.RED  # 1 день из 4 — меньше 50%


def test_control_passes_and_skips_item_in_plan(banked, fixed_clock):
    tutor = banked
    with pytest.raises(AppError, match="нечем"):
        tutor.start_control(MATH, 1)  # в банке по 3 задачи на номер
    tutor.control.config = tutor.control.config.model_copy(update={"tasks": 3, "min_tasks": 3})
    session = tutor.start_control(MATH, 1)
    assert tutor.start_control(MATH, 1).id == session.id  # повторный старт — та же
    assert any(i.kind == PlanItemKind.CONTROL for i in tutor.daily_plan().items)
    while True:
        step = tutor.control_step(session.id)
        if step.attempt is None:
            break
        assert step.attempt.mode == AttemptMode.CONTROL
        assert not tutor.ai_allowed_for(step.attempt.id)
        with pytest.raises(AppError, match="подсказок нет"):
            tutor.next_hint(step.attempt.id)
        fixed_clock.advance(dt.timedelta(minutes=1))
        _solve(tutor, step.attempt)
    done = tutor.control_session(session.id)
    assert done.status == ControlStatus.PASSED and done.passed_tasks == 3
    assert all(r.passed for r in tutor.control_results(session.id))
    control_item = next(i for i in tutor.daily_plan().items if i.kind == PlanItemKind.CONTROL)
    assert control_item.status == PlanItemStatus.DONE
    tutor.rebuild_plan()
    practice = [i for i in tutor.daily_plan().items if i.kind == PlanItemKind.PRACTICE]
    assert all(not (i.subject == MATH and i.exam_item == 1) for i in practice)


def test_control_fails_when_slow_or_unfinished(banked, fixed_clock):
    tutor = banked
    tutor.control.config = tutor.control.config.model_copy(update={"tasks": 3, "min_tasks": 3})
    session = tutor.start_control(MATH, 2)
    step = tutor.control_step(session.id)
    fixed_clock.advance(dt.timedelta(hours=2))  # намного дольше норматива
    _solve(tutor, step.attempt)
    finished = tutor.finish_control(session.id)
    assert finished.status == ControlStatus.FAILED and finished.passed_tasks == 0
    results = tutor.control_results(session.id)
    assert results[0].correct and not results[0].in_time
    assert [r.attempt_id is None for r in results] == [False, True, True]
    with pytest.raises(AppError, match="уже завершена"):
        tutor.finish_control(session.id)
