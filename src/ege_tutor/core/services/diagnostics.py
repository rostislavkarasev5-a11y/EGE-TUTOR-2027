"""Адаптивная диагностика (Phase 5, архитектура 5.9, ADR-0016).

Правила:
- задачи только со статусами из config/diagnostics.toml (по умолчанию REVIEWED);
- без подсказок и без ИИ (подсказки запрещает PracticeService, ИИ в диагностику не передаётся);
- следующая задача — та, что сильнее всего уменьшает неопределённость прогноза балла;
  первая задача по номеру — средней сложности;
- остановка: прогноз точен, бюджет задач или времени исчерпан, задачи почти ничего не дают
  или закончились;
- posterior не хранится: он пересчитывается из попыток сессии, поэтому диагностику можно
  прервать и продолжить;
- при завершении сохраняется предварительный baseline: оценка каждого номера и прогноз.
"""

from collections import Counter
from dataclasses import dataclass

from ege_tutor.config import DiagnosticsConfig
from ege_tutor.core.domain import (
    AnswerKind,
    Attempt,
    AttemptStatus,
    Catalog,
    DiagnosticItemResult,
    DiagnosticObservation,
    DiagnosticSession,
    DiagnosticState,
    DiagnosticStatus,
    ExamSpec,
    ItemBasis,
    ItemEstimate,
    StopReason,
    Subject,
    Task,
    TaskSource,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository, RepositoryError
from ege_tutor.core.services.diagnostics_model import (
    DiagnosticModelState,
    DiagnosticModelV0,
    ItemSpec,
)

FINISHED = (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP)
# При равной пользе сначала официальные задачи, потом свои, потом стартовый банк.
SOURCE_ORDER = {
    TaskSource.OFFICIAL_FIPI: 0,
    TaskSource.OPEN_BANK: 1,
    TaskSource.USER_MATERIAL: 2,
    TaskSource.AI_GENERATED: 3,
}
DEFAULT_DIFFICULTY = 3


@dataclass(frozen=True)
class DiagnosticChoice:
    """Что делать дальше: дать задачу или остановиться."""

    task: Task | None
    stop: StopReason | None


def observation(attempt: Attempt, difficulty: int | None) -> DiagnosticObservation:
    """Ответ попытки так, как его видит модель. «Сдался» — неверно."""
    spent, norm = attempt.time_spent_seconds, attempt.time_norm_seconds
    slow = attempt.correct and spent is not None and bool(norm) and spent > 2 * norm
    return DiagnosticObservation(
        exam_item=attempt.exam_item,
        difficulty=difficulty or DEFAULT_DIFFICULTY,
        correct=attempt.correct,
        slow=slow,
    )


class DiagnosticsService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        config: DiagnosticsConfig,
        catalog: Catalog,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self.config = config
        self._catalog = catalog
        self.model = DiagnosticModelV0(config.model)

    # ── данные ──────────────────────────────────────────────────────────────

    def _spec(self, subject: Subject) -> ExamSpec:
        spec = self._catalog.specs.get(subject)
        if spec is None:
            raise AppError("структура экзамена не загружена")
        return spec

    def _items(self, subject: Subject) -> tuple[ItemSpec, ...]:
        return tuple(ItemSpec(i.number, i.max_points) for i in self._spec(subject).items)

    def eligible_tasks(self, subject: Subject) -> list[Task]:
        """Задачи, которые можно давать в диагностике."""
        allowed = set(self.config.rules.allowed_verification_statuses)
        return [
            t
            for t in self._repo.list_tasks(subject, None, None, limit=100_000)
            if t.verification_status in allowed and t.answer is not None
        ]

    def session(self, session_id: int) -> DiagnosticSession:
        session = self._repo.get_diagnostic_session(session_id)
        if session is None:
            raise AppError(f"диагностика №{session_id} не найдена")
        return session

    def sessions(self, subject: Subject | None = None, limit: int = 20) -> list[DiagnosticSession]:
        return self._repo.list_diagnostic_sessions(subject, limit)

    def active(self, subject: Subject) -> DiagnosticSession | None:
        return self._repo.active_diagnostic_session(subject)

    def attempts(self, session_id: int) -> list[tuple[Attempt, int | None]]:
        return self._repo.diagnostic_attempts(session_id)

    def open_attempt(self, session_id: int) -> Attempt | None:
        """Начатая, но ещё не отвеченная задача сессии."""
        return next(
            (a for a, _ in self.attempts(session_id) if a.status == AttemptStatus.IN_PROGRESS),
            None,
        )

    def session_of_attempt(self, attempt_id: int) -> int | None:
        return self._repo.diagnostic_session_of_attempt(attempt_id)

    # ── состояние ───────────────────────────────────────────────────────────

    def _model_state(
        self, subject: Subject, history: list[tuple[Attempt, int | None]]
    ) -> DiagnosticModelState:
        observations = [observation(a, d) for a, d in history if a.status in FINISHED]
        return self.model.state(self._items(subject), observations)

    def state(self, session_id: int) -> DiagnosticState:
        session = self.session(session_id)
        history = self.attempts(session_id)
        model_state = self._model_state(session.subject, history)
        finished = [a for a, _ in history if a.status in FINISHED]
        answered = Counter(a.exam_item for a in finished)
        has_tasks = {t.exam_item for t in self.eligible_tasks(session.subject)}
        estimates = []
        for item in self._spec(session.subject).items:
            probability, confidence = model_state.item_estimate(item.number)
            if answered[item.number]:
                basis = ItemBasis.DIRECT
            elif item.number in has_tasks:
                basis = ItemBasis.INFERRED
            else:
                basis = ItemBasis.NOT_ASSESSED
            estimates.append(
                ItemEstimate(
                    exam_item=item.number,
                    title=item.title,
                    max_points=item.max_points,
                    probability=probability,
                    confidence=confidence,
                    basis=basis,
                    answered=answered[item.number],
                    answer_only=item.answer_kind == AnswerKind.EXTENDED,
                )
            )
        seconds = sum(a.time_spent_seconds or 0 for a in finished)
        return DiagnosticState(
            session=session,
            estimates=tuple(estimates),
            forecast=model_state.forecast(self.config.stopping.forecast_interval),
            tasks_done=len(finished),
            minutes_spent=seconds / 60,
            max_tasks=self.config.budget.max_tasks_per_subject,
            max_minutes=self.config.budget.max_minutes_per_subject,
        )

    # ── ход диагностики ─────────────────────────────────────────────────────

    def start(self, subject: Subject) -> DiagnosticSession:
        """Начать диагностику по предмету или продолжить начатую."""
        active = self.active(subject)
        if active is not None:
            return active
        if not self.eligible_tasks(subject):
            raise AppError(
                "для диагностики нет проверенных задач. Загрузи стартовый банк: ege bank"
            )
        return self._repo.create_diagnostic_session(subject, self.model.version, self._clock.now())

    def choose(self, session_id: int) -> DiagnosticChoice:
        """Следующая задача диагностики или причина остановиться."""
        session = self.session(session_id)
        if session.status != DiagnosticStatus.ACTIVE:
            raise AppError("эта диагностика уже завершена")
        history = self.attempts(session_id)
        finished = [a for a, _ in history if a.status in FINISHED]
        budget, stopping = self.config.budget, self.config.stopping
        if len(finished) >= budget.max_tasks_per_subject:
            return DiagnosticChoice(None, StopReason.TASK_BUDGET)
        if sum(a.time_spent_seconds or 0 for a in finished) >= budget.max_minutes_per_subject * 60:
            return DiagnosticChoice(None, StopReason.TIME_BUDGET)
        model_state = self._model_state(session.subject, history)
        if model_state.forecast(stopping.forecast_interval).half_width <= (
            stopping.target_half_width_primary
        ):
            return DiagnosticChoice(None, StopReason.PRECISE)

        used = {a.task_id for a, _ in history}
        directly = {a.exam_item for a in finished}
        available: dict[tuple[int, int], list[Task]] = {}
        for task in self.eligible_tasks(session.subject):
            if task.id not in used:
                key = (task.exam_item, task.difficulty or DEFAULT_DIFFICULTY)
                available.setdefault(key, []).append(task)
        if not available:
            return DiagnosticChoice(None, StopReason.NO_TASKS)

        first = self.config.model.first_difficulty
        best: tuple[float, int, int] | None = None
        for item in sorted({number for number, _ in available}):
            levels = sorted(d for number, d in available if number == item)
            if item not in directly:
                # первая задача по номеру — ближайшая к средней сложности
                levels = [min(levels, key=lambda d: (abs(d - first), d))]
            for difficulty in levels:
                gain = model_state.expected_gain(item, difficulty)
                if best is None or gain > best[0]:
                    best = (gain, item, difficulty)
        assert best is not None
        gain, item, difficulty = best
        if gain < stopping.min_information_gain:
            return DiagnosticChoice(None, StopReason.NO_GAIN)
        return DiagnosticChoice(self._pick(available[(item, difficulty)]), None)

    def _pick(self, tasks: list[Task]) -> Task:
        """Из равноценных задач — которую решали реже, официальную, с меньшим номером."""
        stats = self._repo.attempt_stats(t.id for t in tasks)
        return min(tasks, key=lambda t: (stats.get(t.id, (0,))[0], SOURCE_ORDER[t.source], t.id))

    def link(self, session_id: int, attempt_id: int) -> None:
        self._repo.add_diagnostic_attempt(session_id, attempt_id)

    def finish(self, session_id: int, reason: StopReason) -> DiagnosticSession:
        """Завершить диагностику и сохранить предварительный baseline."""
        state = self.state(session_id)
        results = [
            DiagnosticItemResult(
                exam_item=e.exam_item,
                probability=min(1.0, max(0.0, e.probability)),
                confidence=e.confidence,
                basis=e.basis,
                answered=e.answered,
            )
            for e in state.estimates
        ]
        try:
            return self._repo.finish_diagnostic_session(
                session_id,
                status=DiagnosticStatus.FINISHED,
                at=self._clock.now(),
                reason=reason,
                forecast=state.forecast,
                results=results,
            )
        except RepositoryError as e:
            raise AppError(str(e)) from e

    def results(self, session_id: int) -> list[DiagnosticItemResult]:
        return self._repo.diagnostic_results(session_id)

    def baseline(self, subject: Subject) -> DiagnosticSession | None:
        """Последняя завершённая диагностика по предмету."""
        return next(
            (s for s in self.sessions(subject, limit=100) if s.status == DiagnosticStatus.FINISHED),
            None,
        )
