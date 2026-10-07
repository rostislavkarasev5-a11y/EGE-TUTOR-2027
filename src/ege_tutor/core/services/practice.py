"""Решение задач: попытки, таймер, подсказки и проверка ответа (Phase 2).

Правила (архитектура, разделы 5.3 и 5.6):
- решать можно только задачи с проверенным ответом (AUTO_CHECKED, REVIEWED);
- каждая попытка записывается навсегда: ответ, время, подсказки, номер попытки;
- подсказки 1–3 — записанные к задаче, 4 — полное решение, 5 — похожая задача
  (это уже новая попытка на другой задаче);
- самостоятельной считается только верная попытка без подсказок;
- ответ проверяет предметный модуль (subjects/), CORE записывает результат.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from ege_tutor.config import MasteryConfig
from ege_tutor.core.domain import (
    AnswerCheck,
    AnswerType,
    Attempt,
    AttemptMode,
    AttemptStatus,
    Subject,
    Task,
    VerificationStatus,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository, RepositoryError
from ege_tutor.subjects import SubjectTutor

SOLUTION_LEVEL = 4
FINISHED = (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP)


@dataclass(frozen=True)
class ShownHint:
    level: int
    text: str
    independence: float  # коэффициент самостоятельности после этой подсказки


@dataclass(frozen=True)
class AttemptResult:
    attempt: Attempt
    check: AnswerCheck
    task: Task


class PracticeService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        mastery: MasteryConfig,
        tutor_for: Callable[[Subject], SubjectTutor],
        time_norm_of: Callable[[Subject, int], int | None],
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._mastery = mastery
        self._tutor_for = tutor_for
        self._time_norm_of = time_norm_of

    # ── выбор задачи ────────────────────────────────────────────────────────

    def _task(self, task_id: int) -> Task:
        task = self._repo.get_task(task_id)
        if task is None:
            raise AppError(f"задача №{task_id} не найдена")
        return task

    @staticmethod
    def why_not_practicable(task: Task) -> str | None:
        """Почему задачу нельзя решать, или None, если можно."""
        if task.answer_type == AnswerType.EXTENDED:
            return (
                f"задача №{task.id} с развёрнутым ответом: решение по критериям ФИПИ "
                "появится в Phase 8"
            )
        if task.verification_status == VerificationStatus.UNVERIFIED:
            return f"ответ задачи №{task.id} ещё не проверен. Сначала: ege review {task.id}"
        if task.verification_status in (VerificationStatus.DISPUTED, VerificationStatus.REJECTED):
            return f"задача №{task.id} снята с выдачи (статус {task.verification_status})"
        if task.answer is None:
            return f"у задачи №{task.id} нет эталонного ответа"
        return None

    def _candidates(
        self, subject: Subject | None, exam_item: int | None, exclude: int | None = None
    ) -> list[Task]:
        tasks = self._repo.list_tasks(subject, exam_item, None, limit=100_000)
        return [t for t in tasks if t.can_practice and t.id != exclude]

    def _least_practiced(self, tasks: list[Task]) -> list[Task]:
        """Сначала задачи, которые решали реже и давнее всего."""
        stats = self._repo.attempt_stats(t.id for t in tasks)
        never = dt.datetime.min.replace(tzinfo=dt.UTC)
        return sorted(tasks, key=lambda t: (*stats.get(t.id, (0, never)), t.id))

    def next_task(self, subject: Subject | None = None, exam_item: int | None = None) -> Task:
        candidates = self._candidates(subject, exam_item)
        if not candidates:
            existing = self._repo.list_tasks(subject, exam_item, None, limit=100_000)
            short = [t for t in existing if t.answer_type != AnswerType.EXTENDED]
            waiting = [t for t in short if t.verification_status == VerificationStatus.UNVERIFIED]
            if existing and not short:
                raise AppError("здесь только задания с развёрнутым ответом: их решение — Phase 8")
            if waiting:
                raise AppError(
                    f"нет проверенных задач. Непроверенных: {len(waiting)} — "
                    "проверь их ответы командой ege review"
                )
            raise AppError("нет задач для решения. Добавь задачи: ege import ФАЙЛ --apply")
        return self._least_practiced(candidates)[0]

    def similar_task(self, task_id: int) -> Task | None:
        """Похожая задача (подсказка 5): тот же номер ЕГЭ, лучше — с общими навыками."""
        task = self._task(task_id)
        candidates = self._candidates(task.subject, task.exam_item, exclude=task.id)
        if not candidates:
            return None
        ordered = self._least_practiced(candidates)
        shared = [t for t in ordered if set(t.skills) & set(task.skills)]
        return (shared or ordered)[0]

    # ── попытка ─────────────────────────────────────────────────────────────

    def _carried_hint_level(self, task_id: int, now: dt.datetime) -> int:
        """Уровень подсказки, который переходит из недавней неудачной попытки."""
        last = self._repo.last_finished_attempt(task_id)
        if last is None or last.correct or last.finished_at is None:
            return 0
        window = dt.timedelta(hours=self._mastery.attempts.hint_carryover_hours)
        return last.max_hint_level if now - last.finished_at <= window else 0

    def start(self, task_id: int, mode: AttemptMode = AttemptMode.PRACTICE) -> Attempt:
        task = self._task(task_id)
        reason = self.why_not_practicable(task)
        if reason:
            raise AppError(reason)
        now = self._clock.now()
        self._repo.abandon_in_progress(now)
        return self._repo.create_attempt(
            task_id=task.id,
            mode=mode,
            attempt_no=self._repo.count_attempts(task.id, FINISHED) + 1,
            started_at=now,
            max_hint_level=self._carried_hint_level(task.id, now),
            time_norm_seconds=task.time_norm_seconds
            or self._time_norm_of(task.subject, task.exam_item),
        )

    def _open_attempt(self, attempt_id: int) -> Attempt:
        attempt = self._repo.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AppError(f"попытка №{attempt_id} уже завершена")
        return attempt

    def available_hint_levels(self, task: Task) -> list[int]:
        levels = [h.level for h in task.hints]
        if task.solution:
            levels.append(SOLUTION_LEVEL)
        return sorted(levels)

    def next_hint(self, attempt_id: int) -> ShownHint:
        """Следующая подсказка: ближайший записанный уровень выше уже показанного."""
        attempt = self._open_attempt(attempt_id)
        task = self._task(attempt.task_id)
        level = next(
            (lv for lv in self.available_hint_levels(task) if lv > attempt.max_hint_level), None
        )
        if level is None:
            if attempt.max_hint_level >= SOLUTION_LEVEL:
                raise AppError("решение уже показано. Можно взять похожую задачу")
            raise AppError("больше записанных подсказок нет. Можно сдаться и посмотреть ответ")
        text = task.solution if level == SOLUTION_LEVEL else task_hint_text(task, level)
        self._repo.record_hint(attempt.id, level, self._clock.now())
        return ShownHint(
            level=level,
            text=text or "",
            independence=self._mastery.independence.for_hint_level(level),
        )

    def submit(self, attempt_id: int, answer: str) -> AttemptResult:
        attempt = self._open_attempt(attempt_id)
        if not answer.strip():
            raise AppError("пустой ответ")
        task = self._task(attempt.task_id)
        assert task.answer is not None  # гарантирует start()
        check = self._tutor_for(task.subject).check_answer(task.answer_type, task.answer, answer)
        finished = self._repo.finish_attempt(
            attempt.id,
            status=AttemptStatus.ANSWERED,
            at=self._clock.now(),
            answer=answer,
            answer_normalized=check.normalized,
            verdict=check.verdict,
        )
        return AttemptResult(finished, check, task)

    def give_up(self, attempt_id: int) -> Attempt:
        attempt = self._open_attempt(attempt_id)
        return self._repo.finish_attempt(
            attempt.id, status=AttemptStatus.GAVE_UP, at=self._clock.now()
        )

    def abandon(self, attempt_id: int) -> Attempt:
        attempt = self._open_attempt(attempt_id)
        return self._repo.finish_attempt(
            attempt.id, status=AttemptStatus.ABANDONED, at=self._clock.now()
        )

    # ── проверка ответа задачи пользователем ────────────────────────────────

    def review(self, task_id: int, answer_is_correct: bool) -> Task:
        """Пользователь сверил эталонный ответ: REVIEWED или DISPUTED (снять с выдачи)."""
        task = self._task(task_id)
        if task.answer is None:
            raise AppError(f"у задачи №{task_id} нет ответа, проверять нечего")
        status = VerificationStatus.REVIEWED if answer_is_correct else VerificationStatus.DISPUTED
        try:
            return self._repo.set_verification_status(task_id, status, self._clock.now())
        except RepositoryError as e:
            raise AppError(str(e)) from e

    def next_unverified(
        self, subject: Subject | None = None, exam_item: int | None = None
    ) -> Task | None:
        for task in self._repo.list_tasks(subject, exam_item, None, limit=100_000):
            if (
                task.verification_status == VerificationStatus.UNVERIFIED
                and task.answer is not None
            ):
                return task
        return None


def task_hint_text(task: Task, level: int) -> str | None:
    return next((h.text for h in task.hints if h.level == level), None)
