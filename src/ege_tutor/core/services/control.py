"""Контрольная «я это знаю» по номеру ЕГЭ (ADR-0019, п. 8).

Без подсказок и без ИИ. Засчитана, если достаточная доля задач решена верно, самостоятельно
и не дольше норматива × slow_factor. Сданный номер на время выпадает из тренировки в плане.
"""

import datetime as dt
from dataclasses import dataclass

from ege_tutor.config import PlannerControl
from ege_tutor.core.domain import (
    AnswerKind,
    Attempt,
    AttemptStatus,
    Catalog,
    ControlSession,
    ControlStatus,
    ControlTaskResult,
    Subject,
    Task,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository


@dataclass(frozen=True)
class ControlStep:
    """Что сейчас в контрольной: открытая попытка и её задача (или None — контрольная окончена)."""

    session: ControlSession
    attempt: Attempt | None
    task: Task | None


class ControlService:
    def __init__(
        self, repository: Repository, clock: Clock, config: PlannerControl, catalog: Catalog
    ) -> None:
        self._repo = repository
        self._clock = clock
        self.config = config
        self._catalog = catalog

    def eligible_tasks(self, subject: Subject, exam_item: int) -> list[Task]:
        """Проверенные задачи номера, которые ученик не решал последние fresh_days дней.

        Только с кратким ответом: самопроверка части 2 — не замер «я это знаю».
        """
        now = self._clock.now()
        recent = {
            a.task_id
            for a in self._repo.finished_attempts_between(
                now - dt.timedelta(days=self.config.fresh_days), now
            )
        }
        tasks = [
            t
            for t in self._repo.list_tasks(subject, exam_item, None, limit=100_000)
            if t.auto_checkable and t.id not in recent
        ]
        # Разные сложности: сначала по сложности, внутри — по номеру (детерминированно).
        return sorted(tasks, key=lambda t: (t.difficulty or 3, t.id))

    def why_unavailable(self, subject: Subject, exam_item: int) -> str | None:
        spec = self._catalog.specs.get(subject)
        item = spec.item(exam_item) if spec else None
        if item is None:
            return f"в экзамене нет задания №{exam_item}"
        if item.answer_kind == AnswerKind.EXTENDED:
            return (
                f"№{exam_item} — задание с развёрнутым ответом: контрольной по нему нет, "
                "решай его в тренировке с самопроверкой по критериям"
            )
        count = len(self.eligible_tasks(subject, exam_item))
        if count < self.config.min_tasks:
            return (
                f"проверить №{exam_item} нечем: подходящих задач {count}, нужно не меньше "
                f"{self.config.min_tasks} (проверенные и не решавшиеся последние "
                f"{self.config.fresh_days} дней)"
            )
        return None

    def active(self, subject: Subject, exam_item: int) -> ControlSession | None:
        return next(
            (
                c
                for c in self._repo.list_control_sessions(subject, exam_item, limit=5)
                if c.status == ControlStatus.ACTIVE
            ),
            None,
        )

    def start(self, subject: Subject, exam_item: int) -> ControlSession:
        """Начать контрольную по номеру или вернуть уже начатую."""
        current = self.active(subject, exam_item)
        if current is not None:
            return current
        reason = self.why_unavailable(subject, exam_item)
        if reason:
            raise AppError(reason)
        pool = self.eligible_tasks(subject, exam_item)
        chosen = _spread(pool, self.config.tasks)
        limit = sum(t.time_norm_seconds or 0 for t in chosen)
        if not limit:
            spec_item = self._catalog.specs[subject].item(exam_item)
            limit = (spec_item.time_norm_seconds or 0) * len(chosen) if spec_item else 0
        return self._repo.create_control_session(
            subject=subject,
            exam_item=exam_item,
            task_ids=[t.id for t in chosen],
            time_limit_seconds=limit,
            at=self._clock.now(),
        )

    def session(self, session_id: int) -> ControlSession:
        session = self._repo.get_control_session(session_id)
        if session is None:
            raise AppError(f"контрольная №{session_id} не найдена")
        return session

    def sessions(
        self, subject: Subject | None = None, exam_item: int | None = None, limit: int = 20
    ) -> list[ControlSession]:
        return self._repo.list_control_sessions(subject, exam_item, limit)

    def session_of_attempt(self, attempt_id: int) -> int | None:
        return self._repo.control_session_of_attempt(attempt_id)

    def open_attempt(self, session_id: int) -> Attempt | None:
        return next(
            (
                a
                for a in self._repo.control_attempts(session_id)
                if a.status == AttemptStatus.IN_PROGRESS
            ),
            None,
        )

    def next_task_id(self, session_id: int) -> int | None:
        """Следующая задача контрольной, по которой ещё не было попытки."""
        session = self.session(session_id)
        tried = {a.task_id for a in self._repo.control_attempts(session_id)}
        return next((t for t in session.task_ids if t not in tried), None)

    def link(self, session_id: int, attempt_id: int) -> None:
        self._repo.add_control_attempt(session_id, attempt_id)

    def results(self, session_id: int) -> list[ControlTaskResult]:
        """Итог по каждой задаче: верно, самостоятельно, вовремя (норматив × slow_factor)."""
        session = self.session(session_id)
        by_task: dict[int, Attempt] = {}
        for attempt in self._repo.control_attempts(session_id):
            if attempt.status != AttemptStatus.IN_PROGRESS:
                by_task[attempt.task_id] = attempt
        out = []
        for task_id in session.task_ids:
            attempt = by_task.get(task_id)
            if attempt is None:
                out.append(ControlTaskResult(task_id, None, False, False, False, None, None))
                continue
            spent = attempt.time_spent_seconds
            norm = attempt.time_norm_seconds
            in_time = norm is None or (
                spent is not None and spent <= norm * self.config.slow_factor
            )
            out.append(
                ControlTaskResult(
                    task_id=task_id,
                    attempt_id=attempt.id,
                    correct=attempt.correct,
                    independent=attempt.independent,
                    in_time=in_time,
                    seconds=spent,
                    norm_seconds=norm,
                )
            )
        return out

    def finish(self, session_id: int) -> ControlSession:
        """Подвести итог. Нерешённые задачи считаются несданными."""
        session = self.session(session_id)
        if session.status != ControlStatus.ACTIVE:
            raise AppError("эта контрольная уже завершена")
        results = self.results(session_id)
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        ok = total > 0 and passed / total >= self.config.pass_share
        return self._repo.finish_control_session(
            session_id,
            status=ControlStatus.PASSED if ok else ControlStatus.FAILED,
            passed_tasks=passed,
            at=self._clock.now(),
        )


def _spread(pool: list[Task], count: int) -> list[Task]:
    """Взять count задач, равномерно по списку, отсортированному по сложности."""
    if len(pool) <= count:
        return pool
    step = len(pool) / count
    return [pool[int(n * step)] for n in range(count)]
