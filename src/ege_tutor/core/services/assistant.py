"""ИИ-помощник: подсказки, объяснения, разбор ошибок, оценка части 2, похожие задачи.

Phase 6, архитектура раздел 8, ADR-0017. Правила, которые обеспечивает CORE (а не ИИ):
- ИИ предлагает → CORE проверяет и решает → CORE записывает; всё от ИИ помечено
  «ИИ, предварительно» и не меняет проверку ответа;
- в диагностике, контрольной, пробнике и экзамене ИИ недоступен;
- в ИИ уходят только учебные данные: задача, эталон, ответ ученика; личных данных нет;
- каждое обращение записывается с токенами и стоимостью; при достижении месячного
  лимита ИИ выключается до следующего месяца;
- подсказка, раскрывающая ответ, отклоняется; объяснение — только после попытки;
- похожая задача сохраняется как AI_GENERATED и выдаётся, только если её ответ сошёлся
  с независимой проверкой (выражение — SymPy, программа — песочница);
- разговор с репетитором (Phase 6.5, ADR-0018): пока попытка идёт, ответ задачи в ИИ не
  уходит, а реплика, которая его называет, заменяется отказом; первый вопрос до ответа
  засчитывается как подсказка уровня 1.
"""

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ege_tutor.config import AIConfig, SandboxConfig
from ege_tutor.core.domain import (
    MISTAKE_CATEGORY_NAMES,
    AICallStatus,
    AICriterionScore,
    AIError,
    AINote,
    AIPurpose,
    AIStatus,
    AITaskContext,
    AIUsage,
    AnswerType,
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    ChatMessage,
    ChatRole,
    ChatTurn,
    ImportBatch,
    MistakeCategory,
    Part2Grade,
    Part2GradeStatus,
    Subject,
    Task,
    TaskDraft,
    TaskSource,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import (
    AIService,
    Clock,
    Repository,
    RunRequest,
    Sandbox,
    SandboxLimits,
    SandboxUnavailableError,
    SandboxVerdict,
    SpeechService,
)
from ege_tutor.core.services.code import outputs_match
from ege_tutor.core.services.content_import import content_hash
from ege_tutor.subjects import SubjectTutor

# Режимы, где ИИ недоступен: они измеряют, что ученик умеет сам (ADR-0009, ADR-0016).
AI_FORBIDDEN_MODES = frozenset(
    {AttemptMode.DIAGNOSTIC, AttemptMode.CONTROL, AttemptMode.MOCK, AttemptMode.EXAM}
)
MAX_AI_HINT_LEVEL = 3
MIN_SOLUTION_CHARS = 20
MAX_SOLUTION_CHARS = 10_000
FINISHED = (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP)
MAX_QUESTION_CHARS = 1000
CHAT_HISTORY_TURNS = 10
CHAT_HINT_LEVEL = 1  # первый вопрос до ответа = подсказка уровня 1 (ADR-0018)
CHAT_REFUSAL = "Ответ я не скажу, но могу подсказать, с чего начать. Спроси, что именно непонятно."


def month_start(now: dt.datetime) -> dt.datetime:
    """Начало текущего месяца (по UTC): с него считается месячный лимит трат."""
    return now.astimezone(dt.UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _answer_forms(answer: str) -> set[str]:
    forms = {answer.strip()}
    forms |= {f.replace(".", ",") for f in forms} | {f.replace(",", ".") for f in forms}
    return {f for f in forms if f}


def reveals_answer(text: str, answer: str | None) -> bool:
    """Называет ли подсказка ответ задачи.

    Ответ ищется отдельным «словом» (12 не найдётся в 120). Однозначный ответ (например, «2»)
    часто встречается в подсказке и без раскрытия, поэтому он считается раскрытым, только
    если рядом есть слово «ответ».
    """
    if not answer:
        return False
    lowered = text.lower()
    for form in _answer_forms(answer):
        pattern = rf"(?<![\w.,]){re.escape(form.lower())}(?![\w]|[.,]\d)"
        for match in re.finditer(pattern, lowered):
            if len(form) >= 2:
                return True
            nearby = lowered[max(0, match.start() - 30) : match.end() + 30]
            if "ответ" in nearby:
                return True
    return False


@dataclass(frozen=True)
class AIHint:
    level: int
    text: str
    independence: float


@dataclass(frozen=True)
class GeneratedTask:
    """Итог генерации: новая задача и как CORE её проверил."""

    task: Task
    batch: ImportBatch
    check_note: str


class AssistantService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        ai: AIService,
        config: AIConfig,
        catalog: Catalog,
        tutor_for: Callable[[Subject], SubjectTutor],
        sandbox: Sandbox,
        sandbox_config: SandboxConfig,
        independence_for_level: Callable[[int], float],
        asset_root: Path,
        speech: SpeechService | None = None,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._ai = ai
        self.config = config
        self._catalog = catalog
        self._tutor_for = tutor_for
        self._sandbox = sandbox
        self._sandbox_config = sandbox_config
        self._independence = independence_for_level
        self._asset_root = asset_root
        self._speech = speech

    # ── состояние и бюджет ──────────────────────────────────────────────────

    def status(self) -> AIStatus:
        spent, calls = self._repo.ai_usage_since(month_start(self._clock.now()))
        budget = self.config.monthly_budget_rub
        reason = self._ai.unavailable_reason if not self._ai.is_available else None
        if reason is None and spent >= budget:
            reason = (
                f"месячный лимит трат на ИИ исчерпан ({spent:.2f} из {budget:.2f} ₽). "
                "ИИ включится 1-го числа; всё остальное работает"
            )
        if self._speech is None:
            speech_reason: str | None = "голос не настроен"
        elif not self._speech.is_available:
            speech_reason = self._speech.unavailable_reason
        else:
            speech_reason = reason
        return AIStatus(
            available=reason is None,
            reason=reason,
            provider=self._ai.provider,
            model=self._ai.model,
            month_spent_rub=spent,
            monthly_budget_rub=budget,
            month_calls=calls,
            speech_available=speech_reason is None,
            speech_reason=speech_reason,
            voice=self._speech.voice if self._speech is not None else None,
        )

    def _require_available(self) -> None:
        status = self.status()
        if not status.available:
            raise AppError(f"ИИ недоступен: {status.reason}")

    def _record(
        self,
        purpose: AIPurpose,
        status: AICallStatus,
        usage: AIUsage | None,
        *,
        error: str | None = None,
        attempt_id: int | None = None,
        task_id: int | None = None,
    ) -> int:
        cost = self.config.cost_rub(usage.input_tokens, usage.output_tokens) if usage else 0.0
        call = self._repo.add_ai_call(
            purpose=purpose,
            status=status,
            model=usage.model if usage else self._ai.model,
            usage=usage,
            cost_rub=cost,
            at=self._clock.now(),
            error=error,
            attempt_id=attempt_id,
            task_id=task_id,
        )
        return call.id

    def _failed(
        self, purpose: AIPurpose, error: AIError, attempt_id: int | None, task_id: int | None
    ) -> AppError:
        self._record(
            purpose,
            AICallStatus.ERROR,
            error.usage,
            error=str(error),
            attempt_id=attempt_id,
            task_id=task_id,
        )
        return AppError(f"ИИ не помог: {error}")

    def _rejected(
        self,
        purpose: AIPurpose,
        usage: AIUsage,
        reason: str,
        attempt_id: int | None = None,
        task_id: int | None = None,
    ) -> AppError:
        self._record(
            purpose,
            AICallStatus.REJECTED,
            usage,
            error=reason,
            attempt_id=attempt_id,
            task_id=task_id,
        )
        return AppError(f"ответ ИИ отклонён: {reason}")

    # ── данные ──────────────────────────────────────────────────────────────

    def _task(self, task_id: int) -> Task:
        task = self._repo.get_task(task_id)
        if task is None:
            raise AppError(f"задача №{task_id} не найдена")
        return task

    def _attempt(self, attempt_id: int) -> Attempt:
        attempt = self._repo.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        if attempt.mode in AI_FORBIDDEN_MODES:
            raise AppError(
                "в диагностике, контрольной, пробнике и экзамене ИИ недоступен: "
                "они измеряют, что ты умеешь сам"
            )
        return attempt

    @staticmethod
    def context(task: Task) -> AITaskContext:
        """Что о задаче уходит в ИИ: только учебные данные."""
        return AITaskContext(
            subject=task.subject,
            exam_item=task.exam_item,
            statement=task.statement,
            answer_type=task.answer_type,
            answer=task.answer,
            solution=task.solution,
            file_names=tuple(a.file_name for a in task.assets),
        )

    def notes(self, attempt_id: int) -> list[AINote]:
        return self._repo.list_ai_notes(attempt_id=attempt_id)

    def hint_texts(self, attempt_id: int) -> dict[int, str]:
        """Тексты ИИ-подсказок попытки по уровням."""
        return {
            n.hint_level: n.text
            for n in self._repo.list_ai_notes(attempt_id=attempt_id, purpose=AIPurpose.HINT)
            if n.hint_level is not None
        }

    def can_use_in(self, attempt: Attempt) -> bool:
        return attempt.mode not in AI_FORBIDDEN_MODES

    # ── подсказка ───────────────────────────────────────────────────────────

    def ai_hint_level(self, attempt: Attempt, task: Task) -> int | None:
        """Какой уровень подсказки может дать ИИ сейчас, или None.

        ИИ дополняет записанные подсказки, а не заменяет их: если у задачи есть записанная
        подсказка следующего уровня, сначала показывается она.
        """
        if attempt.status != AttemptStatus.IN_PROGRESS or attempt.mode in AI_FORBIDDEN_MODES:
            return None
        level = attempt.max_hint_level + 1
        if level > MAX_AI_HINT_LEVEL:
            return None
        if any(attempt.max_hint_level < h.level <= MAX_AI_HINT_LEVEL for h in task.hints):
            return None
        return level

    def hint(self, attempt_id: int, previous: list[str]) -> AIHint:
        """ИИ-подсказка уровня 1–3; засчитывается как обычная подсказка этого уровня."""
        attempt = self._attempt(attempt_id)
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AppError(f"попытка №{attempt_id} уже завершена")
        task = self._task(attempt.task_id)
        level = self.ai_hint_level(attempt, task)
        if level is None:
            if attempt.max_hint_level >= MAX_AI_HINT_LEVEL:
                raise AppError("ИИ даёт подсказки уровней 1–3; дальше — записанное решение")
            raise AppError("у задачи есть записанная подсказка: открой её кнопкой «Подсказка»")
        self._require_available()
        try:
            reply = self._ai.hint(self.context(task), level, previous)
        except AIError as e:
            raise self._failed(AIPurpose.HINT, e, attempt.id, task.id) from e
        if reveals_answer(reply.text, task.answer):
            raise self._rejected(
                AIPurpose.HINT, reply.usage, "подсказка раскрывала ответ", attempt.id, task.id
            )
        call_id = self._record(
            AIPurpose.HINT, AICallStatus.OK, reply.usage, attempt_id=attempt.id, task_id=task.id
        )
        now = self._clock.now()
        self._repo.record_hint(attempt.id, level, now)
        self._repo.add_ai_note(
            ai_call_id=call_id,
            purpose=AIPurpose.HINT,
            text=reply.text,
            at=now,
            attempt_id=attempt.id,
            task_id=task.id,
            hint_level=level,
        )
        return AIHint(level, reply.text, self._independence(level))

    # ── объяснение после попытки ────────────────────────────────────────────

    def explanation(self, attempt_id: int) -> AINote | None:
        notes = self._repo.list_ai_notes(attempt_id=attempt_id, purpose=AIPurpose.EXPLAIN)
        return notes[-1] if notes else None

    def explain(self, attempt_id: int) -> AINote:
        """Объяснение решения. Только после ответа или «сдаюсь»: иначе это раскрытие ответа."""
        attempt = self._attempt(attempt_id)
        if attempt.status not in FINISHED:
            raise AppError("объяснение доступно после ответа или после «Сдаюсь»")
        existing = self.explanation(attempt_id)
        if existing is not None:
            return existing
        task = self._task(attempt.task_id)
        self._require_available()
        try:
            reply = self._ai.explain(self.context(task), attempt.answer)
        except AIError as e:
            raise self._failed(AIPurpose.EXPLAIN, e, attempt.id, task.id) from e
        call_id = self._record(
            AIPurpose.EXPLAIN,
            AICallStatus.OK,
            reply.usage,
            attempt_id=attempt.id,
            task_id=task.id,
        )
        return self._repo.add_ai_note(
            ai_call_id=call_id,
            purpose=AIPurpose.EXPLAIN,
            text=reply.text,
            at=self._clock.now(),
            attempt_id=attempt.id,
            task_id=task.id,
        )

    # ── разбор ошибки ───────────────────────────────────────────────────────

    def mistake_note(self, mistake_id: int) -> AINote | None:
        notes = self._repo.list_ai_notes(mistake_id=mistake_id, purpose=AIPurpose.MISTAKE)
        return notes[-1] if notes else None

    def classify_mistake(self, mistake_id: int) -> AINote:
        """Предложение ИИ, к какой категории отнести ошибку. Принимает его пользователь."""
        mistake = self._repo.get_mistake(mistake_id)
        if mistake is None:
            raise AppError(f"ошибка №{mistake_id} не найдена")
        existing = self.mistake_note(mistake_id)
        if existing is not None:
            return existing
        attempt = self._attempt(mistake.attempt_id)
        task = self._task(mistake.task_id)
        runs = self._repo.list_code_runs(attempt_id=attempt.id, limit=1)
        output = (runs[0].stdout + "\n" + runs[0].stderr).strip() if runs else None
        categories = [f"{c.value} — {MISTAKE_CATEGORY_NAMES[c]}" for c in MistakeCategory]
        self._require_available()
        try:
            reply = self._ai.classify_mistake(
                self.context(task), attempt.answer, categories, output
            )
        except AIError as e:
            raise self._failed(AIPurpose.MISTAKE, e, attempt.id, task.id) from e
        try:
            category = MistakeCategory(reply.category)
        except ValueError:
            raise self._rejected(
                AIPurpose.MISTAKE,
                reply.usage,
                f"категории «{reply.category}» нет в списке",
                attempt.id,
                task.id,
            ) from None
        call_id = self._record(
            AIPurpose.MISTAKE,
            AICallStatus.OK,
            reply.usage,
            attempt_id=attempt.id,
            task_id=task.id,
        )
        return self._repo.add_ai_note(
            ai_call_id=call_id,
            purpose=AIPurpose.MISTAKE,
            text=reply.explanation,
            at=self._clock.now(),
            attempt_id=attempt.id,
            task_id=task.id,
            mistake_id=mistake.id,
            category=category,
            confidence=min(1.0, max(0.0, reply.confidence)),
        )

    # ── разговор с репетитором (Phase 6.5, ADR-0018) ────────────────────────

    def chat_messages(self, attempt_id: int) -> list[ChatMessage]:
        return self._repo.list_chat_messages(attempt_id)

    def can_chat(self, attempt: Attempt) -> bool:
        return attempt.mode not in AI_FORBIDDEN_MODES and attempt.status != AttemptStatus.ABANDONED

    def ask(self, attempt_id: int, question: str) -> ChatMessage:
        """Ответ репетитора на вопрос ученика. Возвращает реплику репетитора.

        Пока попытка идёт, ответа задачи ИИ не знает, а реплика, которая его всё же называет,
        заменяется отказом. Первый принятый вопрос до ответа засчитывается как подсказка
        уровня 1: иначе с репетитором можно решить задачу «самостоятельно».
        """
        attempt = self._attempt(attempt_id)
        if attempt.status == AttemptStatus.ABANDONED:
            raise AppError("попытка брошена: начни задачу заново, чтобы спросить репетитора")
        text = " ".join(question.split())
        if not text:
            raise AppError("напиши вопрос")
        if len(text) > MAX_QUESTION_CHARS:
            raise AppError(f"вопрос длиннее {MAX_QUESTION_CHARS} символов: спроси короче")
        task = self._task(attempt.task_id)
        self._require_available()
        finished = attempt.status in FINISHED
        history = [
            ChatTurn(m.role == ChatRole.STUDENT, m.text)
            for m in self._repo.list_chat_messages(attempt.id)[-CHAT_HISTORY_TURNS:]
        ]
        try:
            reply = self._ai.chat(self.context(task), history, text, finished=finished)
        except AIError as e:
            raise self._failed(AIPurpose.CHAT, e, attempt.id, task.id) from e
        now = self._clock.now()
        self._repo.add_chat_message(attempt_id=attempt.id, role=ChatRole.STUDENT, text=text, at=now)
        if not finished and (
            reveals_answer(reply.text, task.answer) or reveals_answer(reply.speech, task.answer)
        ):
            call_id = self._record(
                AIPurpose.CHAT,
                AICallStatus.REJECTED,
                reply.usage,
                error="реплика раскрывала ответ задачи",
                attempt_id=attempt.id,
                task_id=task.id,
            )
            return self._repo.add_chat_message(
                attempt_id=attempt.id,
                role=ChatRole.TUTOR,
                text=CHAT_REFUSAL,
                speech=CHAT_REFUSAL,
                at=now,
                ai_call_id=call_id,
            )
        call_id = self._record(
            AIPurpose.CHAT, AICallStatus.OK, reply.usage, attempt_id=attempt.id, task_id=task.id
        )
        if not finished and attempt.max_hint_level < CHAT_HINT_LEVEL:
            self._repo.record_hint(attempt.id, CHAT_HINT_LEVEL, now)
        return self._repo.add_chat_message(
            attempt_id=attempt.id,
            role=ChatRole.TUTOR,
            text=reply.text,
            speech=reply.speech,
            at=now,
            ai_call_id=call_id,
        )

    # ── часть 2 ─────────────────────────────────────────────────────────────

    def _max_points(self, task: Task) -> int:
        spec = self._catalog.specs.get(task.subject)
        item = spec.item(task.exam_item) if spec else None
        if item is None:
            raise AppError(f"номер {task.exam_item} не найден в структуре экзамена")
        return item.max_points

    def grade_part2(self, task_id: int, solution_text: str) -> Part2Grade:
        """Предварительная оценка развёрнутого решения ИИ. В mastery не идёт (Phase 8)."""
        task = self._task(task_id)
        if task.answer_type != AnswerType.EXTENDED:
            raise AppError("оценка по критериям — только для заданий с развёрнутым решением")
        text = solution_text.strip()
        if len(text) < MIN_SOLUTION_CHARS:
            raise AppError("решение слишком короткое: опиши ход решения")
        if len(text) > MAX_SOLUTION_CHARS:
            raise AppError("решение длиннее 10 000 символов")
        max_points = self._max_points(task)
        self._require_available()
        try:
            reply = self._ai.grade_part2(self.context(task), text, max_points)
        except AIError as e:
            raise self._failed(AIPurpose.PART2, e, None, task.id) from e
        # CORE не верит баллам на слово: каждый критерий — в своих пределах, сумма — не выше
        # максимума задания.
        criteria = tuple(
            AICriterionScore(c.name, min(c.points, c.max_points), c.max_points, c.comment)
            for c in reply.criteria
        )
        points = min(sum(c.points for c in criteria), max_points)
        call_id = self._record(AIPurpose.PART2, AICallStatus.OK, reply.usage, task_id=task.id)
        return self._repo.add_part2_grade(
            task_id=task.id,
            solution_text=text,
            points=points,
            max_points=max_points,
            criteria=criteria,
            summary=reply.summary,
            status=Part2GradeStatus.AI_PRELIMINARY,
            at=self._clock.now(),
            ai_call_id=call_id,
        )

    def part2_grades(self, task_id: int | None = None) -> list[Part2Grade]:
        return self._repo.list_part2_grades(task_id)

    def part2_grade(self, grade_id: int) -> Part2Grade:
        grade = self._repo.get_part2_grade(grade_id)
        if grade is None:
            raise AppError(f"оценка №{grade_id} не найдена")
        return grade

    # ── похожая задача ──────────────────────────────────────────────────────

    @staticmethod
    def why_cannot_generate(task: Task) -> str | None:
        if task.answer_type == AnswerType.EXTENDED:
            return "похожие задачи с развёрнутым решением ИИ пока не составляет"
        if task.assets:
            return "к задаче приложены файлы: такие задачи ИИ не составляет"
        if task.answer is None:
            return "у образца нет ответа"
        return None

    def _check_math(self, task: Task, answer: str, check: str) -> tuple[bool, str]:
        tutor = self._tutor_for(task.subject)
        verdict = tutor.check_answer(task.answer_type, answer, check).verdict
        ok = verdict in (Verdict.CORRECT, Verdict.WRONG_FORMAT)
        return ok, f"ответ сверен с выражением ИИ «{check}» (SymPy)"

    def _check_code(self, answer: str, code: str) -> tuple[bool | None, str]:
        if not self._sandbox.is_available:
            return None, "песочница недоступна — ответ не проверен"
        limits = SandboxLimits(
            time_limit_seconds=self._sandbox_config.time_limit_seconds,
            memory_limit_mb=self._sandbox_config.memory_limit_mb,
        )
        try:
            result = self._sandbox.run(RunRequest(code=code, limits=limits))
        except SandboxUnavailableError:
            return None, "песочница недоступна — ответ не проверен"
        if result.verdict != SandboxVerdict.OK:
            return False, f"программа ИИ не отработала ({result.verdict})"
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        ok = bool(lines) and outputs_match(lines[-1], answer)
        return ok, "ответ сверен с программой ИИ в песочнице"

    def _normalized_answer(self, task: Task, answer: str) -> str | None:
        """Ответ в форме, как его хранит банк, или None, если так на бланке не записать."""
        if task.answer_type == AnswerType.NUMBER:
            value = answer.strip().replace(",", ".")
            return value if re.fullmatch(r"-?\d+(?:\.\d+)?", value) else None
        if task.answer_type == AnswerType.SEQUENCE:
            parts = answer.split()
            return " ".join(parts) if len(parts) >= 2 else None
        return answer.strip() or None

    def generate_similar(self, task_id: int) -> GeneratedTask:
        """Похожая задача от ИИ. Сохраняется, только если CORE подтвердил ответ."""
        task = self._task(task_id)
        reason = self.why_cannot_generate(task)
        if reason:
            raise AppError(reason)
        self._require_available()
        try:
            reply = self._ai.generate_similar(self.context(task))
        except AIError as e:
            raise self._failed(AIPurpose.GENERATE, e, None, task.id) from e
        answer = self._normalized_answer(task, reply.answer)
        if answer is None:
            raise self._rejected(
                AIPurpose.GENERATE,
                reply.usage,
                f"ответ «{reply.answer}» нельзя записать на бланке",
                task_id=task.id,
            )
        if task.subject == Subject.INFORMATICS:
            ok, note = self._check_code(answer, reply.check)
        else:
            ok, note = self._check_math(task, answer, reply.check)
        if ok is False:
            raise self._rejected(
                AIPurpose.GENERATE,
                reply.usage,
                f"ответ ИИ не сошёлся с проверкой: {note}",
                task_id=task.id,
            )
        digest = content_hash(task.subject, task.exam_item, reply.statement)
        if self._repo.active_task_hashes({digest}):
            raise self._rejected(
                AIPurpose.GENERATE,
                reply.usage,
                "такая задача уже есть в банке",
                task_id=task.id,
            )
        status = VerificationStatus.AUTO_CHECKED if ok else VerificationStatus.UNVERIFIED
        call_id = self._record(AIPurpose.GENERATE, AICallStatus.OK, reply.usage, task_id=task.id)
        draft = TaskDraft(
            subject=task.subject,
            exam_item=task.exam_item,
            statement=reply.statement,
            answer_type=task.answer_type,
            answer=answer,
            solution=reply.solution,
            difficulty=task.difficulty,
            time_norm_seconds=task.time_norm_seconds,
            source=TaskSource.AI_GENERATED,
            source_ref=f"ИИ ({reply.usage.model}), по образцу задачи №{task.id}",
            source_version=reply.usage.model,
            verification_status=status,
            skills=task.skills,
            asset_paths=(),
            content_hash=digest,
        )
        batch = self._repo.add_import_batch(
            file_name=f"ИИ: похожая на задачу №{task.id}",
            file_format="AI",
            drafts=[draft],
            asset_root=self._asset_root,
            rejected_count=0,
            report={"ai_call_id": call_id, "check": note, "status": status.value},
            created_at=self._clock.now(),
        )
        created = self._repo.list_tasks(task.subject, task.exam_item, None, limit=100_000)
        new_task = next(t for t in created if t.content_hash == digest)
        return GeneratedTask(new_task, batch, note)
