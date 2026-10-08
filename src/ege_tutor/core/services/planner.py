"""Расписание, план на день, правило 80/20, объективные причины и дисциплина (ADR-0019).

План строит детерминированный алгоритм, без ИИ. Выполнение пунктов не отмечается вручную:
оно считается по завершённым попыткам за день. Все числа — в config/planner.toml.
"""

import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from ege_tutor.config import PlannerConfig
from ege_tutor.core.domain import (
    Attempt,
    AttemptMode,
    CalendarEvent,
    CalendarWindow,
    Catalog,
    ControlStatus,
    DailyCheckin,
    DailyPlan,
    DayBudget,
    DiagnosticStatus,
    DisciplineColor,
    DisciplineDay,
    DisciplineReport,
    EventKind,
    MasteryAggregate,
    PlanItem,
    PlanItemKind,
    PlanItemStatus,
    ReviewItem,
    ReviewReason,
    Subject,
    Task,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository

# Попытки этих режимов засчитываются в тренировку, повторения и задачи на ошибку.
TRAINING_MODES = frozenset({AttemptMode.PRACTICE, AttemptMode.HOMEWORK, AttemptMode.REVIEW})
MAX_NOTE_CHARS = 300
MAX_PLAN_DAYS_AHEAD = 60
SUBJECT_NAMES = {Subject.MATH_PROFILE: "математика", Subject.INFORMATICS: "информатика"}


@dataclass(frozen=True)
class PlannerSources:
    """Что планировщик берёт из других сервисов CORE (без доступа к их внутренностям)."""

    review_queue: Callable[[], list[ReviewItem]]
    mastery_by_exam_item: Callable[[Subject], list[MasteryAggregate]]
    task_for_skill: Callable[[str], Task | None]
    diagnostic_tasks: Callable[[Subject], int]
    profile_offset: Callable[[], int | None]


def _minute(t: dt.time) -> int:
    return t.hour * 60 + t.minute


def parse_time(text: str) -> dt.time:
    """«16:30» → время. 24:00 не принимается: окно заканчивается не позже 23:59."""
    try:
        hours, minutes = (int(part) for part in text.strip().split(":"))
        return dt.time(hours, minutes)
    except ValueError:
        raise AppError(f"время пишется как ЧЧ:ММ, например 16:30, а не «{text}»") from None


class PlannerService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        config: PlannerConfig,
        catalog: Catalog,
        sources: PlannerSources,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self.config = config
        self._catalog = catalog
        self._src = sources

    # ── день ученика ────────────────────────────────────────────────────────

    def offset_hours(self) -> int:
        offset = self._src.profile_offset()
        return self.config.day.default_utc_offset_hours if offset is None else offset

    def _tz(self) -> dt.timezone:
        return dt.timezone(dt.timedelta(hours=self.offset_hours()))

    def now_local(self) -> dt.datetime:
        return self._clock.now().astimezone(self._tz())

    def today(self) -> dt.date:
        return self.now_local().date()

    def _day_bounds(self, day: dt.date) -> tuple[dt.datetime, dt.datetime]:
        start = dt.datetime.combine(day, dt.time(), tzinfo=self._tz())
        return start, start + dt.timedelta(days=1)

    # ── шаблон недели и события ─────────────────────────────────────────────

    def windows(self) -> list[CalendarWindow]:
        return self._repo.list_windows()

    def add_window(self, weekday: int, start: dt.time, end: dt.time) -> CalendarWindow:
        if not 0 <= weekday <= 6:
            raise AppError("день недели — от понедельника до воскресенья")
        if _minute(end) <= _minute(start):
            raise AppError("окно должно заканчиваться позже, чем начинается")
        for window in self._repo.list_windows():
            if window.weekday == weekday and (
                _minute(start) < _minute(window.end) and _minute(window.start) < _minute(end)
            ):
                raise AppError(
                    f"окно пересекается с уже заданным {window.weekday_name} "
                    f"{window.start:%H:%M}–{window.end:%H:%M}"
                )
        return self._repo.add_window(weekday, _minute(start), _minute(end))

    def delete_window(self, window_id: int) -> None:
        if not self._repo.delete_window(window_id):
            raise AppError(f"окно №{window_id} не найдено")

    def events(self, start: dt.date | None = None, days: int = 30) -> list[CalendarEvent]:
        first = start or self.today()
        begin = dt.datetime.combine(first, dt.time())
        return self._repo.list_events(begin, begin + dt.timedelta(days=days))

    def add_event(
        self,
        kind: EventKind,
        title: str,
        starts_at: dt.datetime,
        ends_at: dt.datetime,
        blocks_study: bool,
    ) -> CalendarEvent:
        text = " ".join(title.split()) or EventKind(kind).name
        if len(text) > 200:
            raise AppError("название события не длиннее 200 символов")
        if ends_at <= starts_at:
            raise AppError("событие должно заканчиваться позже, чем начинается")
        if ends_at - starts_at > dt.timedelta(days=60):
            raise AppError("событие не длиннее 60 дней: длинное раздели на части")
        return self._repo.add_event(
            kind=kind,
            title=text,
            starts_at=starts_at.replace(tzinfo=None),
            ends_at=ends_at.replace(tzinfo=None),
            blocks_study=blocks_study,
            at=self._clock.now(),
        )

    def delete_event(self, event_id: int) -> None:
        if not self._repo.delete_event(event_id):
            raise AppError(f"событие №{event_id} не найдено")

    # ── чек-ин и время на день ──────────────────────────────────────────────

    def checkin(self, day: dt.date | None = None) -> DailyCheckin | None:
        return self._repo.get_checkin(day or self.today())

    def save_checkin(
        self, fatigue: int, available_minutes: int | None = None, note: str | None = None
    ) -> DailyCheckin:
        if not 1 <= fatigue <= 5:
            raise AppError("усталость — от 1 (бодр) до 5 (очень устал)")
        if available_minutes is not None and not 0 <= available_minutes <= 1440:
            raise AppError("свободное время — от 0 до 1440 минут")
        text = " ".join((note or "").split()) or None
        if text is not None and len(text) > 500:
            raise AppError("комментарий не длиннее 500 символов")
        checkin = DailyCheckin(self.today(), fatigue, available_minutes, text)
        self._repo.save_checkin(checkin, self._clock.now())
        return checkin

    def _day_has_windows(self, day: dt.date, windows: list[CalendarWindow]) -> bool:
        return not windows or any(w.weekday == day.weekday() for w in windows)

    def budget(self, day: dt.date | None = None) -> DayBudget:
        """Сколько минут на учёбу: окна − события «мешает учёбе», с поправкой на чек-ин."""
        day = day or self.today()
        cfg = self.config.day
        windows = self._repo.list_windows()
        lines: list[str] = []
        free = [False] * 1440
        template_empty = not windows
        if template_empty:
            window_minutes = cfg.default_minutes
            lines.append(f"шаблон недели не заполнен: беру {cfg.default_minutes} мин")
        else:
            for w in windows:
                if w.weekday == day.weekday():
                    for m in range(_minute(w.start), _minute(w.end)):
                        free[m] = True
            window_minutes = sum(free)
            lines.append(f"окна для учёбы в этот день: {window_minutes} мин")
        start = dt.datetime.combine(day, dt.time())
        blocked = 0
        for event in self._repo.list_events(start, start + dt.timedelta(days=1)):
            if not event.blocks_study:
                continue
            first = max(0, int((event.starts_at - start).total_seconds() // 60))
            last = min(1440, math.ceil((event.ends_at - start).total_seconds() / 60))
            if template_empty:
                if last - first >= 12 * 60:  # событие почти на весь день — учёбы нет
                    blocked = window_minutes
                continue
            taken = sum(1 for m in range(first, last) if free[m])
            for m in range(first, last):
                free[m] = False
            if taken:
                blocked += taken
                lines.append(f"{event.kind_name} «{event.title}»: −{taken} мин")
        if template_empty and blocked:
            lines.append("событие занимает весь день")
        minutes = max(0, window_minutes - blocked)
        checkin = self._repo.get_checkin(day)
        factor = cfg.fatigue_factor(checkin.fatigue if checkin else None)
        if checkin and checkin.available_minutes is not None:
            if checkin.available_minutes < minutes:
                lines.append(f"по чек-ину реально есть {checkin.available_minutes} мин")
            minutes = min(minutes, checkin.available_minutes)
        if factor < 1:
            lines.append(f"усталость {checkin.fatigue if checkin else '?'}/5: × {factor:g}")
        minutes = math.floor(minutes * factor)
        if minutes < cfg.min_plan_minutes:
            if minutes > 0 or window_minutes > 0:
                lines.append(f"меньше {cfg.min_plan_minutes} мин — сегодня выходной")
            elif not template_empty:
                lines.append("сегодня окон для учёбы нет — выходной")
            minutes = 0
        return DayBudget(
            day=day,
            minutes=minutes,
            window_minutes=window_minutes,
            blocked_minutes=blocked,
            fatigue_factor=factor,
            template_empty=template_empty,
            lines=tuple(lines),
        )

    # ── сколько времени на задачу ───────────────────────────────────────────

    def task_minutes(self, subject: Subject, exam_item: int) -> int:
        spec = self._catalog.specs.get(subject)
        item = spec.item(exam_item) if spec else None
        if item is None or not item.time_norm_seconds:
            return self.config.plan.default_task_minutes
        return max(1, math.ceil(item.time_norm_seconds * self.config.plan.time_factor / 60))

    # ── построение плана ────────────────────────────────────────────────────

    def _practicable(self, subject: Subject) -> list[Task]:
        return [
            t for t in self._repo.list_tasks(subject, None, None, limit=100_000) if t.can_practice
        ]

    def _gap_factor(self, subject: Subject) -> tuple[float, str]:
        """Множитель разрыва: доля первичных баллов, которых не хватает до максимума."""
        cfg = self.config.plan
        for session in self._repo.list_diagnostic_sessions(subject, limit=20):
            if session.status == DiagnosticStatus.FINISHED and session.forecast is not None:
                f = session.forecast
                gap = max(cfg.min_gap_factor, 1 - f.mean / f.max_points)
                return gap, f"прогноз {f.mean:.0f} из {f.max_points} первичных"
        return 1.0, "прогноза ещё нет"

    def subject_shares(self, subjects: list[Subject]) -> dict[Subject, float]:
        if not subjects:
            return {}
        if len(subjects) == 1:
            return {subjects[0]: 1.0}
        weights = {s: self._gap_factor(s)[0] for s in subjects}
        total = sum(weights.values())
        low = self.config.plan.min_subject_share
        shares = {s: w / total for s, w in weights.items()}
        for _ in range(len(subjects)):
            small = [s for s, v in shares.items() if v < low]
            if not small:
                break
            rest = [s for s in subjects if s not in small]
            spare = 1 - low * len(small)
            rest_total = sum(weights[s] for s in rest) or 1.0
            shares = {s: low for s in small} | {s: spare * weights[s] / rest_total for s in rest}
        return shares

    def _skipped_items(self, subject: Subject) -> set[int]:
        """Номера, по которым недавно сдана контрольная «я это знаю»."""
        since = self._clock.now() - dt.timedelta(days=self.config.control.skip_days)
        return {
            c.exam_item
            for c in self._repo.list_control_sessions(subject, limit=200)
            if c.status == ControlStatus.PASSED and c.finished_at and c.finished_at >= since
        }

    def _draft(
        self,
        day: dt.date,
        kind: PlanItemKind,
        subject: Subject,
        tasks: int,
        minutes: int,
        reason: str,
        *,
        exam_item: int | None = None,
        skill_code: str | None = None,
    ) -> PlanItem:
        return PlanItem(
            id=0,
            day=day,
            position=0,
            kind=kind,
            subject=subject,
            exam_item=exam_item,
            skill_code=skill_code,
            tasks=tasks,
            minutes=max(1, minutes),
            mandatory=False,
            added_by_user=False,
            stored_status=PlanItemStatus.PLANNED,
            reason=reason,
            note=None,
            carried_from=None,
        )

    def _generate(self, day: dt.date, budget: int, kept: list[PlanItem]) -> list[PlanItem]:
        """Новые пункты в порядке: диагностика → повторения → ошибки → тренировка."""
        cfg = self.config.plan
        used = sum(i.minutes for i in kept if i.active)
        taken_skills = {i.skill_code for i in kept if i.skill_code}
        taken_items = {(i.subject, i.exam_item) for i in kept if i.kind == PlanItemKind.PRACTICE}
        subjects = [s for s in Subject if self._practicable(s)]
        out: list[PlanItem] = []

        def fit(item: PlanItem, per_task: int) -> PlanItem | None:
            nonlocal used
            left = budget - used
            if item.minutes <= left:
                used += item.minutes
                return item
            tasks = left // per_task if per_task else 0
            if item.kind != PlanItemKind.DIAGNOSTIC and tasks >= 1:
                used += tasks * per_task
                return replace(item, tasks=tasks, minutes=tasks * per_task)
            return None

        # 1. Диагностика, если по предмету её ещё не было.
        for subject in Subject:
            if any(i.kind == PlanItemKind.DIAGNOSTIC and i.subject == subject for i in kept):
                continue
            if not self._src.diagnostic_tasks(subject):
                continue
            sessions = self._repo.list_diagnostic_sessions(subject, limit=50)
            if any(s.status == DiagnosticStatus.FINISHED for s in sessions):
                continue
            minutes = min(cfg.diagnostic_minutes, budget - used)
            if minutes < self.config.day.min_plan_minutes:
                continue
            draft = self._draft(
                day,
                PlanItemKind.DIAGNOSTIC,
                subject,
                1,
                minutes,
                f"по предмету «{SUBJECT_NAMES[subject]}» ещё нет диагностики: без неё план "
                "не знает слабых номеров",
            )
            used += minutes
            out.append(draft)

        # 2. Повторения, у которых подошёл срок; 3. открытые паттерны ошибок.
        queue = self._src.review_queue()
        forgetting = [q for q in queue if q.reason == ReviewReason.FORGETTING]
        mistakes = sorted(
            (q for q in queue if q.reason == ReviewReason.MISTAKES),
            key=lambda q: -(q.priority or 0),
        )
        for entry, kind, tasks in [
            *((q, PlanItemKind.REVIEW, cfg.review_tasks) for q in forgetting),
            *((q, PlanItemKind.MISTAKE, cfg.mistake_tasks) for q in mistakes),
        ]:
            if entry.skill_code in taken_skills:
                continue
            task = self._src.task_for_skill(entry.skill_code)
            if task is None:
                continue
            per_task = self.task_minutes(task.subject, task.exam_item)
            if kind == PlanItemKind.REVIEW:
                late = (day - entry.due_on).days if entry.due_on else 0
                when = f"срок был {late} дн. назад" if late > 0 else "срок сегодня"
                value = f", освоение {entry.value:.2f}" if entry.value is not None else ""
                reason = f"повторение «{entry.skill_title}»: {when}{value}"
            else:
                category = entry.category.name if entry.category else ""
                from ege_tutor.core.domain import MISTAKE_CATEGORY_NAMES

                if entry.category is not None:
                    category = MISTAKE_CATEGORY_NAMES[entry.category]
                reason = f"частая ошибка «{category}» в навыке «{entry.skill_title}»"
            draft = self._draft(
                day,
                kind,
                entry.subject,
                tasks,
                tasks * per_task,
                reason,
                skill_code=entry.skill_code,
            )
            placed = fit(draft, per_task)
            if placed is not None:
                taken_skills.add(entry.skill_code)
                out.append(placed)

        # 4. Тренировка слабых номеров, время делится между предметами по разрыву.
        left = budget - used
        if left <= 0 or not subjects:
            return out
        shares = self.subject_shares(subjects)
        ranked: dict[Subject, list[tuple[float, int, str]]] = {}
        for subject in subjects:
            practicable_items = {t.exam_item for t in self._practicable(subject)}
            skipped = self._skipped_items(subject)
            gap, gap_text = self._gap_factor(subject)
            spec = self._catalog.specs.get(subject)
            masteries = {int(a.key): a for a in self._src.mastery_by_exam_item(subject)}
            rows = []
            for number in sorted(practicable_items - skipped):
                if (subject, number) in taken_items:
                    continue
                spec_item = spec.item(number) if spec else None
                points = spec_item.max_points if spec_item else 1
                agg = masteries.get(number)
                value = agg.value if agg and agg.value is not None else None
                m = self.config.plan.unstudied_mastery if value is None else value
                priority = points * (1 - m) * gap
                studied = f"освоение {value:.2f}" if value is not None else "ещё не изучали"
                why = f"№{number}: {studied}, вес {points} б., {gap_text}"
                rows.append((priority, number, why))
            ranked[subject] = sorted(rows, key=lambda r: (-r[0], r[1]))

        def place(subject: Subject, number: int, why: str, minutes_left: int) -> int:
            per_task = self.task_minutes(subject, number)
            tasks = min(cfg.max_tasks_per_item, minutes_left // per_task)
            if tasks < 1:
                return 0
            out.append(
                self._draft(
                    day,
                    PlanItemKind.PRACTICE,
                    subject,
                    tasks,
                    tasks * per_task,
                    f"тренировка {why}",
                    exam_item=number,
                )
            )
            taken_items.add((subject, number))
            return tasks * per_task

        remaining = left
        for subject in subjects:
            share_left = math.floor(left * shares[subject])
            for _, number, why in ranked[subject]:
                if share_left <= 0 or remaining <= 0:
                    break
                spent = place(subject, number, why, min(share_left, remaining))
                share_left -= spent
                remaining -= spent
        # Остаток (если доля одного предмета не заполнилась) — по общему приоритету.
        rest = sorted(
            (
                (priority, subject, number, why)
                for subject in subjects
                for priority, number, why in ranked[subject]
                if (subject, number) not in taken_items
            ),
            key=lambda r: (-r[0], r[1], r[2]),
        )
        for _, subject, number, why in rest:
            if remaining <= 0:
                break
            remaining -= place(subject, number, why, remaining)
        return out

    def _assign_mandatory(self, items: list[PlanItem], budget: int) -> list[PlanItem]:
        """Обязательные — первые пункты, пока они укладываются в mandatory_share бюджета."""
        cap = budget * self.config.plan.mandatory_share
        running = sum(i.minutes for i in items if i.mandatory)
        result = []
        for item in items:
            if item.mandatory:
                result.append(item)
                continue
            first = running == 0 and not any(r.mandatory for r in result)
            if running + item.minutes <= cap or first:
                running += item.minutes
                result.append(replace(item, mandatory=True))
            else:
                result.append(item)
        return result

    def _explanation(self, budget: DayBudget) -> str:
        if budget.day_off:
            return "; ".join(budget.lines) or "сегодня выходной"
        return "; ".join([*budget.lines, f"итого {budget.minutes} мин"])

    def _build(self, day: dt.date) -> None:
        budget = self.budget(day)
        kept = self._repo.plan_items(day)  # перенесённые на этот день
        new = [] if budget.day_off else self._generate(day, budget.minutes, kept)
        start = max((i.position for i in kept), default=0)
        new = [replace(item, position=start + n) for n, item in enumerate(new, 1)]
        new = self._assign_mandatory(new, max(0, budget.minutes - sum(i.minutes for i in kept)))
        self._repo.save_plan(
            day,
            built_at=self._clock.now(),
            budget_minutes=budget.minutes,
            explanation=self._explanation(budget),
        )
        self._repo.add_plan_items(new, self._clock.now())

    def plan(self, day: dt.date | None = None, *, build: bool = True) -> DailyPlan | None:
        """План дня с выполнением. Сегодняшний план строится при первом обращении."""
        today = self.today()
        day = day or today
        self.close_past_days()
        if day > today + dt.timedelta(days=MAX_PLAN_DAYS_AHEAD):
            raise AppError("план строится не дальше чем на 60 дней вперёд")
        plan = self._repo.get_plan(day)
        if plan is None:
            if not build or day < today:
                return None
            self._build(day)
            plan = self._repo.get_plan(day)
            assert plan is not None
        return self._with_progress(plan, day < today)

    def rebuild(self) -> DailyPlan:
        """Перестроить план на сегодня: начатые, перенесённые и свои пункты остаются."""
        day = self.today()
        plan = self.plan(day)
        assert plan is not None
        removable = [
            i.id
            for i in plan.items
            if i.stored_status == PlanItemStatus.PLANNED
            and not i.added_by_user
            and i.carried_from is None
            and i.done_tasks == 0
        ]
        self._repo.delete_plan_items(removable)
        self._build(day)
        rebuilt = self.plan(day)
        assert rebuilt is not None
        return rebuilt

    # ── выполнение по попыткам ──────────────────────────────────────────────

    def _with_progress(self, plan: DailyPlan, day_over: bool) -> DailyPlan:
        done = self._progress(plan.day, list(plan.items))
        items = tuple(i.with_progress(done.get(i.id, 0), day_over) for i in plan.items)
        return replace(plan, items=items)

    def _progress(self, day: dt.date, items: list[PlanItem]) -> dict[int, int]:
        start, end = self._day_bounds(day)
        done: dict[int, int] = {}
        active = [i for i in items if i.active]
        for item in active:
            if item.kind == PlanItemKind.DIAGNOSTIC:
                finished = any(
                    s.status == DiagnosticStatus.FINISHED
                    and s.finished_at is not None
                    and s.finished_at < end
                    for s in self._repo.list_diagnostic_sessions(item.subject, limit=50)
                )
                done[item.id] = 1 if finished else 0
            elif item.kind == PlanItemKind.CONTROL:
                finished = any(
                    c.status != ControlStatus.ACTIVE
                    and c.finished_at is not None
                    and start <= c.finished_at < end
                    for c in self._repo.list_control_sessions(item.subject, item.exam_item)
                )
                done[item.id] = item.tasks if finished else 0
        training = [
            i for i in active if i.kind not in (PlanItemKind.DIAGNOSTIC, PlanItemKind.CONTROL)
        ]
        if not training:
            return done
        tasks: dict[int, Task | None] = {}
        for attempt in self._repo.finished_attempts_between(start, end):
            if attempt.mode not in TRAINING_MODES:
                continue
            if attempt.task_id not in tasks:
                tasks[attempt.task_id] = self._repo.get_task(attempt.task_id)
            task = tasks[attempt.task_id]
            if task is None:
                continue
            for item in training:
                if done.get(item.id, 0) >= item.tasks or not self._matches(item, attempt, task):
                    continue
                done[item.id] = done.get(item.id, 0) + 1
                break
        return done

    @staticmethod
    def _matches(item: PlanItem, attempt: Attempt, task: Task) -> bool:
        if item.kind == PlanItemKind.PRACTICE:
            return attempt.subject == item.subject and attempt.exam_item == item.exam_item
        return item.skill_code is not None and item.skill_code in task.skills

    # ── правило 80/20 ───────────────────────────────────────────────────────

    def _item(self, item_id: int) -> PlanItem:
        item = self._repo.get_plan_item(item_id)
        if item is None:
            raise AppError(f"пункт плана №{item_id} не найден")
        return item

    def _current(self, item_id: int) -> tuple[PlanItem, DailyPlan]:
        """Пункт с выполнением; менять можно только сегодняшние и будущие пункты."""
        item = self._item(item_id)
        if item.day < self.today():
            raise AppError("прошедший день менять нельзя")
        plan = self._repo.get_plan(item.day)
        if plan is None:
            return item, DailyPlan(item.day, self._clock.now(), 0, "", (item,))
        plan = self._with_progress(plan, False)
        current = next(i for i in plan.items if i.id == item_id)
        return current, plan

    def change_limit(self, plan: DailyPlan) -> tuple[int, int]:
        """(сколько минут ученик уже поменял, сколько можно) за день."""
        used = sum(
            i.minutes
            for i in plan.items
            if i.added_by_user
            or i.stored_status == PlanItemStatus.REMOVED
            or (i.stored_status == PlanItemStatus.MOVED and not i.mandatory)
        )
        return used, math.floor(plan.budget_minutes * self.config.plan.user_change_share)

    def _check_change(self, plan: DailyPlan, minutes: int) -> None:
        used, limit = self.change_limit(plan)
        if used + minutes > limit:
            raise AppError(
                f"по правилу 80/20 сам можно поменять не больше {limit} мин плана на день, "
                f"уже поменяно {used} мин. Обязательные пункты можно только перенести с причиной"
            )

    def _clean_note(self, note: str | None, required: bool, what: str) -> str | None:
        text = " ".join((note or "").split()) or None
        if required and text is None:
            raise AppError(f"{what}: напиши причину")
        if text is not None and len(text) > MAX_NOTE_CHARS:
            raise AppError(f"причина не длиннее {MAX_NOTE_CHARS} символов")
        return text

    def _carry(self, item: PlanItem, to_day: dt.date, note: str) -> PlanItem:
        position = max((i.position for i in self._repo.plan_items(to_day)), default=0) + 1
        [copy] = self._repo.add_plan_items(
            [
                replace(
                    item,
                    day=to_day,
                    position=position,
                    stored_status=PlanItemStatus.PLANNED,
                    note=note,
                    carried_from=item.day,
                    done_tasks=0,
                    day_over=False,
                )
            ],
            self._clock.now(),
        )
        return copy

    def move_item(self, item_id: int, to_day: dt.date, note: str | None) -> PlanItem:
        item, plan = self._current(item_id)
        if not item.open:
            raise AppError("переносить можно только невыполненный пункт плана")
        if to_day <= item.day:
            raise AppError("перенести можно только на один из следующих дней")
        if to_day > self.today() + dt.timedelta(days=MAX_PLAN_DAYS_AHEAD):
            raise AppError("не дальше чем на 60 дней вперёд")
        text = self._clean_note(note, item.mandatory, "обязательный пункт переносится с причиной")
        if not item.mandatory:
            self._check_change(plan, item.minutes)
        self._repo.update_plan_item(item.id, status=PlanItemStatus.MOVED, note=text or "")
        return self._carry(item, to_day, text or f"перенесено с {item.day:%d.%m}")

    def remove_item(self, item_id: int) -> PlanItem:
        item, plan = self._current(item_id)
        if item.mandatory:
            raise AppError(
                "обязательный пункт убрать нельзя: его можно только перенести с причиной"
            )
        if not item.open:
            raise AppError("убрать можно только невыполненный пункт плана")
        if not item.added_by_user:
            self._check_change(plan, item.minutes)
        return self._repo.update_plan_item(item.id, status=PlanItemStatus.REMOVED)

    def add_item(self, subject: Subject, exam_item: int, tasks: int) -> PlanItem:
        day = self.today()
        plan = self.plan(day)
        assert plan is not None
        spec = self._catalog.specs.get(subject)
        if spec is None or spec.item(exam_item) is None:
            raise AppError(f"в экзамене нет задания №{exam_item}")
        if not 1 <= tasks <= self.config.plan.max_tasks_per_item:
            raise AppError(f"задач в пункте — от 1 до {self.config.plan.max_tasks_per_item}")
        if not any(t.exam_item == exam_item for t in self._practicable(subject)):
            raise AppError(f"по №{exam_item} нет проверенных задач для решения")
        minutes = tasks * self.task_minutes(subject, exam_item)
        self._check_change(plan, minutes)
        position = max((i.position for i in plan.items), default=0) + 1
        draft = self._draft(
            day,
            PlanItemKind.PRACTICE,
            subject,
            tasks,
            minutes,
            f"№{exam_item}: добавил ты",
            exam_item=exam_item,
        )
        [item] = self._repo.add_plan_items(
            [replace(draft, position=position, added_by_user=True)], self._clock.now()
        )
        return item

    def move_up(self, item_id: int, up: bool = True) -> None:
        """Поменять порядок: пункт выше или ниже соседа."""
        item, plan = self._current(item_id)
        active = sorted(plan.active_items, key=lambda i: (i.position, i.id))
        index = next(n for n, i in enumerate(active) if i.id == item.id)
        other = index - 1 if up else index + 1
        if not 0 <= other < len(active):
            return
        a, b = active[index], active[other]
        a_pos, b_pos = (
            (b.position, a.position) if a.position != b.position else (b.position, b.position + 1)
        )
        self._repo.update_plan_item(a.id, position=a_pos)
        self._repo.update_plan_item(b.id, position=b_pos)

    # ── объективные причины ─────────────────────────────────────────────────

    def _next_study_day(self, after: dt.date) -> dt.date:
        windows = self._repo.list_windows()
        for n in range(1, self.config.plan.carry_search_days + 1):
            day = after + dt.timedelta(days=n)
            if self._day_has_windows(day, windows):
                return day
        return after + dt.timedelta(days=1)

    def excuse_item(self, item_id: int, note: str | None) -> PlanItem | None:
        """Объективная причина: пункт не портит дисциплину; обязательный переносится."""
        item, _ = self._current(item_id)
        if not item.open:
            raise AppError("причину можно указать только для невыполненного пункта")
        text = self._clean_note(note, True, "объективная причина")
        assert text is not None
        self._repo.update_plan_item(item.id, status=PlanItemStatus.EXCUSED, note=text)
        if item.mandatory:
            return self._carry(item, self._next_study_day(item.day), f"объективная причина: {text}")
        return None

    def excuse_day(self, note: str | None) -> int:
        """Объективная причина на весь сегодняшний день. Возвращает число снятых пунктов."""
        plan = self.plan(self.today())
        assert plan is not None
        text = self._clean_note(note, True, "объективная причина")
        count = 0
        for item in plan.items:
            if item.open:
                self.excuse_item(item.id, text)
                count += 1
        if not count:
            raise AppError("в плане на сегодня нет невыполненных пунктов")
        return count

    # ── дисциплина ──────────────────────────────────────────────────────────

    def close_past_days(self) -> None:
        """Подвести итог каждого прошедшего дня с планом (один раз, задним числом не меняется)."""
        today = self.today()
        for day in self._repo.unclosed_plan_days(today):
            plan = self._repo.get_plan(day)
            if plan is None:
                continue
            plan = self._with_progress(plan, True)
            due = [i for i in plan.active_items if i.mandatory]
            self._repo.save_discipline_day(
                DisciplineDay(
                    day=day,
                    due_minutes=sum(i.minutes for i in due),
                    done_minutes=round(sum(i.minutes * i.done_share for i in due), 2),
                    due_items=len(due),
                    done_items=sum(1 for i in due if i.done_share >= 1),
                    excused=any(i.stored_status == PlanItemStatus.EXCUSED for i in plan.items),
                ),
                self._clock.now(),
            )

    def discipline(self) -> DisciplineReport:
        cfg = self.config.discipline
        self.close_past_days()
        today = self.today()
        start = today - dt.timedelta(days=cfg.window_days)
        days = self._repo.list_discipline_days(start, today - dt.timedelta(days=1))
        counted = [d for d in days if d.counted]
        streak = 0
        for d in reversed(counted):
            if d.done_minutes > 0:
                break
            streak += 1
        window = self.config.excuses.window_days
        excuse_days = len(
            {
                i.day
                for i in self._repo.plan_items_between(today - dt.timedelta(days=window - 1), today)
                if i.stored_status == PlanItemStatus.EXCUSED
            }
        )
        frequent = excuse_days > self.config.excuses.warn_days
        if not counted:
            message = "Пока нет закрытых дней с обязательным планом: оценка появится завтра."
            return DisciplineReport(
                None, None, 0, 0, 0, 0, excuse_days, frequent, message, tuple(days)
            )
        due = sum(d.due_minutes for d in counted)
        done = sum(d.done_minutes for d in counted)
        share = done / due
        if share < cfg.orange or streak >= cfg.red_streak_days:
            color = DisciplineColor.RED
        elif share < cfg.yellow:
            color = DisciplineColor.ORANGE
        elif share < cfg.green:
            color = DisciplineColor.YELLOW
        else:
            color = DisciplineColor.GREEN
        due_items = sum(d.due_items for d in counted)
        done_items = sum(d.done_items for d in counted)
        parts = [
            f"За {cfg.window_days} дн. выполнено {done_items} из {due_items} обязательных "
            f"пунктов ({share:.0%} обязательного времени)."
        ]
        if streak >= cfg.red_streak_days:
            parts.append(f"{streak} дн. подряд выполнимый план не выполнялся совсем.")
        if frequent:
            parts.append(f"Часто объективные причины: {excuse_days} дн. за {window} дн.")
        return DisciplineReport(
            color=color,
            share=share,
            days_counted=len(counted),
            due_items=due_items,
            done_items=done_items,
            missed_streak=streak,
            excuse_days=excuse_days,
            excuses_frequent=frequent,
            message=" ".join(parts),
            days=tuple(days),
        )
