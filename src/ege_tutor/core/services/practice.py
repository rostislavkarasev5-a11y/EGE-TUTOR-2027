"""Решение задач: попытки, таймер, подсказки и проверка ответа (Phase 2).

Правила (архитектура, разделы 5.3 и 5.6):
- решать можно только задачи с проверенным ответом (AUTO_CHECKED, REVIEWED);
- каждая попытка записывается навсегда: ответ, время, подсказки, номер попытки;
- подсказки 1–3 — записанные к задаче, 4 — полное решение, 5 — похожая задача
  (это уже новая попытка на другой задаче);
- самостоятельной считается только верная попытка без подсказок;
- ответ проверяет предметный модуль (subjects/), CORE записывает результат;
- задание части 2 в тренировке, домашке и повторении решается на бумаге и проверяется
  самопроверкой по критериям (Phase 8, ADR-0022): ученик выбирает уровень, CORE записывает
  балл; если есть оценка ИИ к этой попытке, в прогресс идёт меньшая из двух.
"""

import datetime as dt
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

from ege_tutor.config import MasteryConfig
from ege_tutor.core.domain import (
    AICriterionScore,
    AnswerCheck,
    AnswerType,
    Attempt,
    AttemptMode,
    AttemptStatus,
    Part2GradeStatus,
    Subject,
    Task,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository, RepositoryError
from ege_tutor.subjects import SubjectTutor

SOLUTION_LEVEL = 4
FINISHED = (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP)
# Подсказка без текста: уровень засчитан за вопрос репетитору (ADR-0018).
CHAT_HINT_TEXT = "Засчитана за вопрос репетитору."
# Режимы без подсказок: диагностика (ADR-0016). Правило обеспечивает CORE, а не интерфейс.
NO_HINT_MODES = frozenset({AttemptMode.DIAGNOSTIC, AttemptMode.CONTROL})
# Режимы, где задание части 2 проверяется самопроверкой (ADR-0022, п. 5). В контрольной,
# пробнике и экзамене самооценка не годится: они измеряют результат без поблажек.
SELF_CHECK_MODES = frozenset({AttemptMode.PRACTICE, AttemptMode.HOMEWORK, AttemptMode.REVIEW})
SELF_CHECK_ANSWER = "самопроверка: {points} из {max_points}"


def final_answer_type(answer: str) -> AnswerType:
    """Как проверять итоговый ответ задачи части 2: одно число или несколько через «;»."""
    return AnswerType.SEQUENCE if len(answer.replace(";", " ").split()) > 1 else AnswerType.NUMBER


def _final_answer(text: str) -> str:
    return " ".join(text.replace(";", " ").split())


@dataclass(frozen=True)
class ShownHint:
    level: int
    text: str
    independence: float  # коэффициент самостоятельности после этой подсказки
    by_ai: bool = False  # подсказка от ИИ (Phase 6): показывается с пометкой «ИИ, предварительно»


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
    def why_not_practicable(task: Task, mode: AttemptMode = AttemptMode.PRACTICE) -> str | None:
        """Почему задачу нельзя решать, или None, если можно.

        Задание части 2: в диагностике — по итоговому ответу (ADR-0016); в тренировке,
        домашке и повторении — с самопроверкой по эталонному решению (ADR-0022); в контрольной,
        пробнике и экзамене — нельзя.
        """
        extended = task.answer_type == AnswerType.EXTENDED
        self_check = extended and mode in SELF_CHECK_MODES
        if extended and mode == AttemptMode.DIAGNOSTIC and task.answer is None:
            return f"у задачи №{task.id} нет итогового ответа: в диагностике её не проверить"
        if extended and mode not in SELF_CHECK_MODES and mode != AttemptMode.DIAGNOSTIC:
            return (
                f"задача №{task.id} с развёрнутым ответом: в этом режиме часть 2 не проверяется, "
                "решай её в тренировке с самопроверкой"
            )
        if task.verification_status == VerificationStatus.UNVERIFIED:
            return f"ответ задачи №{task.id} ещё не проверен. Сначала: ege review {task.id}"
        if task.verification_status in (VerificationStatus.DISPUTED, VerificationStatus.REJECTED):
            return f"задача №{task.id} снята с выдачи (статус {task.verification_status})"
        if self_check:
            if not (task.solution and task.solution.strip()):
                return f"у задачи №{task.id} нет эталонного решения: самопроверку не с чем сравнить"
            return None
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
            waiting = [
                t for t in existing if t.verification_status == VerificationStatus.UNVERIFIED
            ]
            extended = [t for t in existing if t.answer_type == AnswerType.EXTENDED]
            if existing and len(extended) == len(existing) and not waiting:
                raise AppError(
                    "здесь только задания с развёрнутым ответом без эталонного решения: "
                    "самопроверку не с чем сравнить. Добавь задачи с решением"
                )
            if waiting:
                raise AppError(
                    f"нет проверенных задач. Непроверенных: {len(waiting)} — "
                    "проверь их ответы командой ege review"
                )
            raise AppError("нет задач для решения. Добавь задачи: ege import ФАЙЛ --apply")
        return self._least_practiced(candidates)[0]

    def tasks_for_skill(self, skill_code: str) -> list[Task]:
        """Проверенные задачи на навык: сначала те, которые решали реже и давнее всего."""
        return self._least_practiced(
            [t for t in self._candidates(None, None) if skill_code in t.skills]
        )

    def task_for_skill(self, skill_code: str) -> Task | None:
        """Проверенная задача на навык: которую решали реже и давнее всего (для повторения)."""
        candidates = [t for t in self._candidates(None, None) if skill_code in t.skills]
        return self._least_practiced(candidates)[0] if candidates else None

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
        reason = self.why_not_practicable(task, mode)
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
        if attempt.mode in NO_HINT_MODES:
            where = "в диагностике" if attempt.mode == AttemptMode.DIAGNOSTIC else "в контрольной"
            raise AppError(f"{where} подсказок нет: она измеряет, что ты умеешь сам")
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

    def shown_hints(
        self, attempt_id: int, ai_texts: Mapping[int, str] | None = None
    ) -> list[ShownHint]:
        """Подсказки, уже показанные в этой попытке, по порядку показа.

        ai_texts — тексты подсказок от ИИ по уровням (их хранит ИИ-помощник).
        """
        ai_texts = ai_texts or {}
        attempt = self._repo.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        task = self._task(attempt.task_id)
        shown = []
        for event in self._repo.list_hint_events(attempt_id):
            text = (
                task.solution
                if event.level == SOLUTION_LEVEL
                else task_hint_text(task, event.level)
            )
            by_ai = text is None and event.level in ai_texts
            shown.append(
                ShownHint(
                    level=event.level,
                    text=ai_texts[event.level] if by_ai else text or CHAT_HINT_TEXT,
                    independence=self._mastery.independence.for_hint_level(event.level),
                    by_ai=by_ai,
                )
            )
        return shown

    def submit(self, attempt_id: int, answer: str) -> AttemptResult:
        attempt = self._open_attempt(attempt_id)
        if not answer.strip():
            raise AppError("пустой ответ")
        task = self._task(attempt.task_id)
        if task.answer_type == AnswerType.EXTENDED and attempt.mode != AttemptMode.DIAGNOSTIC:
            raise AppError(
                "задание части 2 проверяется самопроверкой: сравни решение с эталоном "
                "и выбери уровень по критериям"
            )
        assert task.answer is not None  # гарантирует start()
        tutor = self._tutor_for(task.subject)
        if task.answer_type == AnswerType.EXTENDED:
            # часть 2 в диагностике: сверяется только итоговый ответ
            check = tutor.check_answer(
                final_answer_type(task.answer), _final_answer(task.answer), _final_answer(answer)
            )
        else:
            check = tutor.check_answer(task.answer_type, task.answer, answer)
        finished = self._repo.finish_attempt(
            attempt.id,
            status=AttemptStatus.ANSWERED,
            at=self._clock.now(),
            answer=answer,
            answer_normalized=check.normalized,
            verdict=check.verdict,
        )
        return AttemptResult(finished, check, task)

    def self_check_attempt(self, attempt_id: int) -> tuple[Attempt, Task]:
        """Открытая попытка на задание части 2, которую можно проверить самопроверкой."""
        attempt = self._open_attempt(attempt_id)
        task = self._task(attempt.task_id)
        if task.answer_type != AnswerType.EXTENDED:
            raise AppError("самопроверка — только для заданий с развёрнутым ответом")
        if attempt.mode not in SELF_CHECK_MODES:
            raise AppError("в этом режиме самопроверки нет")
        return attempt, task

    def self_grade(
        self, attempt_id: int, points: int, max_points: int, level_text: str
    ) -> AttemptResult:
        """Записать самопроверку части 2 и завершить попытку.

        Балл попытки — самооценка, а если к попытке есть оценка ИИ, — меньшая из двух
        (ADR-0022, п. 5). Полный балл — верно, иначе — неверно. Оценка SELF записывается
        отдельной строкой, рядом с оценкой ИИ. Эталонное решение при самопроверке видно,
        но это не подсказка: уровень подсказки не меняется.
        """
        attempt, task = self.self_check_attempt(attempt_id)
        if not 0 <= points <= max_points:
            raise AppError(f"балл должен быть от 0 до {max_points}")
        now = self._clock.now()
        ai_grades = [
            g
            for g in self._repo.list_part2_grades(attempt_id=attempt.id)
            if g.status == Part2GradeStatus.AI_PRELIMINARY
        ]
        counted = min(points, ai_grades[0].points) if ai_grades else points
        self._repo.add_part2_grade(
            task_id=task.id,
            solution_text="",
            points=points,
            max_points=max_points,
            criteria=(AICriterionScore(level_text, points, max_points, "самопроверка"),),
            summary=level_text,
            status=Part2GradeStatus.SELF,
            at=now,
            attempt_id=attempt.id,
        )
        verdict = Verdict.CORRECT if counted == max_points else Verdict.WRONG
        answer = SELF_CHECK_ANSWER.format(points=points, max_points=max_points)
        finished = self._repo.finish_attempt(
            attempt.id,
            status=AttemptStatus.ANSWERED,
            at=now,
            answer=answer,
            answer_normalized=answer,
            verdict=verdict,
            points=counted,
            max_points=max_points,
        )
        if counted < points:
            note = (
                f"Самооценка {points} из {max_points}, оценка ИИ {counted} из {max_points}: "
                f"в прогресс идёт меньшая — {counted} из {max_points}."
            )
        else:
            note = f"В прогресс идёт {counted} из {max_points}."
        return AttemptResult(finished, AnswerCheck(verdict, answer, note), task)

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
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        exclude: Collection[int] = (),
    ) -> Task | None:
        """Следующая задача, ответ которой нужно сверить. exclude — пропущенные задачи."""
        for task in self._repo.list_tasks(subject, exam_item, None, limit=100_000):
            if (
                task.verification_status == VerificationStatus.UNVERIFIED
                and task.answer is not None
                and task.id not in exclude
            ):
                return task
        return None


def task_hint_text(task: Task, level: int) -> str | None:
    return next((h.text for h in task.hints if h.level == level), None)
