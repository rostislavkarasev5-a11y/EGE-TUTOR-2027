"""ИИ-слой: что CORE отправляет ИИ, что получает и что записывает (Phase 6, ADR-0017).

ИИ предлагает → CORE проверяет и решает → CORE записывает. Всё, что пришло от ИИ, хранится
с пометкой «ИИ, предварительно» и никогда не меняет проверку ответа и mastery само по себе.
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.mastery import MistakeCategory
from ege_tutor.core.domain.subject import Subject
from ege_tutor.core.domain.task import AnswerType

AI_LABEL = "ИИ, предварительно"


class AIPurpose(StrEnum):
    HINT = "HINT"  # подсказка уровня 1–3 к задаче без записанной подсказки
    EXPLAIN = "EXPLAIN"  # объяснение решения после попытки
    MISTAKE = "MISTAKE"  # предложение, к какой категории отнести ошибку
    PART2 = "PART2"  # предварительная оценка развёрнутого решения
    GENERATE = "GENERATE"  # похожая задача
    CHAT = "CHAT"  # ответ на вопрос ученика (Phase 6.5, ADR-0018)
    SPEECH = "SPEECH"  # озвучка текста (SpeechKit)
    LISTEN = "LISTEN"  # распознавание вопроса, заданного голосом (SpeechKit)


AI_PURPOSE_NAMES: dict[AIPurpose, str] = {
    AIPurpose.HINT: "подсказка",
    AIPurpose.EXPLAIN: "объяснение",
    AIPurpose.MISTAKE: "разбор ошибки",
    AIPurpose.PART2: "оценка части 2",
    AIPurpose.GENERATE: "похожая задача",
    AIPurpose.CHAT: "вопрос репетитору",
    AIPurpose.SPEECH: "озвучка",
    AIPurpose.LISTEN: "распознавание голоса",
}


class AICallStatus(StrEnum):
    OK = "OK"  # ответ принят CORE
    REJECTED = "REJECTED"  # ответ пришёл, но CORE его отклонил (например, раскрыл ответ)
    ERROR = "ERROR"  # ответа нет: сеть, ключ, неверный формат


class Part2GradeStatus(StrEnum):
    AI_PRELIMINARY = "AI_PRELIMINARY"  # предварительная оценка ИИ
    # SELF (самопроверка) и CONFIRMED появятся в Phase 8


# ── запросы: только учебные данные, без личных (ADR-0017, п. 5) ──────────────


@dataclass(frozen=True)
class AITaskContext:
    """Задача так, как её видит ИИ. Имени, целей и расписания ученика здесь нет."""

    subject: Subject
    exam_item: int
    statement: str
    answer_type: AnswerType
    answer: str | None
    solution: str | None
    file_names: tuple[str, ...] = ()


# ── ответы ИИ ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AIUsage:
    """Сколько стоил вызов: модель и токены (из ответа API)."""

    model: str
    input_tokens: int
    output_tokens: int
    request_hash: str


@dataclass(frozen=True)
class AIText:
    text: str
    usage: AIUsage


@dataclass(frozen=True)
class AIMistakeSuggestion:
    category: str  # строка: CORE сам проверит, что такая категория есть
    confidence: float
    explanation: str
    usage: AIUsage


@dataclass(frozen=True)
class AICriterionScore:
    name: str
    points: int
    max_points: int
    comment: str


@dataclass(frozen=True)
class AIPart2Suggestion:
    criteria: tuple[AICriterionScore, ...]
    summary: str
    usage: AIUsage


@dataclass(frozen=True)
class AITaskSuggestion:
    """Похожая задача от ИИ. check — выражение (математика) или программа (информатика)."""

    statement: str
    answer: str
    solution: str
    check: str
    usage: AIUsage


@dataclass(frozen=True)
class AIChatReply:
    """Ответ репетитора: text — для экрана, speech — тот же ответ для чтения вслух."""

    text: str
    speech: str
    usage: AIUsage


@dataclass(frozen=True)
class ChatTurn:
    """Реплика разговора, которую CORE передаёт ИИ как историю."""

    from_student: bool
    text: str


class AIError(Exception):
    """ИИ не ответил или ответил не по формату. usage — если вызов всё равно стоил денег."""

    def __init__(self, message: str, usage: AIUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


# ── что записывает CORE ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AICall:
    """Запись о каждом обращении к ИИ: для учёта расходов и отладки."""

    id: int
    purpose: AIPurpose
    status: AICallStatus
    model: str
    input_tokens: int
    output_tokens: int
    cost_rub: float
    request_hash: str
    created_at: dt.datetime
    error: str | None = None
    attempt_id: int | None = None
    task_id: int | None = None


@dataclass(frozen=True)
class AINote:
    """Принятый ответ ИИ: подсказка, объяснение или разбор ошибки."""

    id: int
    purpose: AIPurpose
    text: str
    created_at: dt.datetime
    attempt_id: int | None = None
    task_id: int | None = None
    mistake_id: int | None = None
    hint_level: int | None = None
    category: MistakeCategory | None = None  # для разбора ошибки
    confidence: float | None = None


class ChatRole(StrEnum):
    STUDENT = "STUDENT"
    TUTOR = "TUTOR"


@dataclass(frozen=True)
class ChatMessage:
    """Реплика разговора с репетитором (ADR-0018). Хранится навсегда, как и попытки."""

    id: int
    attempt_id: int
    role: ChatRole
    text: str
    created_at: dt.datetime
    speech: str | None = None  # для чтения вслух (только у репетитора)
    ai_call_id: int | None = None


@dataclass(frozen=True)
class Part2Grade:
    """Оценка развёрнутого решения. В Phase 6 — только предварительная оценка ИИ."""

    id: int
    task_id: int
    solution_text: str
    points: int
    max_points: int
    criteria: tuple[AICriterionScore, ...]
    summary: str
    status: Part2GradeStatus
    created_at: dt.datetime
    attempt_id: int | None = None


@dataclass(frozen=True)
class AIStatus:
    """Можно ли сейчас пользоваться ИИ и сколько потрачено в этом месяце."""

    available: bool
    reason: str | None  # почему недоступен
    provider: str
    model: str
    month_spent_rub: float
    monthly_budget_rub: float
    month_calls: int
    speech_available: bool = False  # голос репетитора (ADR-0018)
    speech_reason: str | None = None
    voice: str | None = None


# ── голос (Phase 6.5, ADR-0018) ─────────────────────────────────────────────


class SpeechError(Exception):
    """SpeechKit не ответил или ответил ошибкой. billable — стоил ли вызов денег."""

    def __init__(self, message: str, *, billable: bool = False) -> None:
        super().__init__(message)
        self.billable = billable
