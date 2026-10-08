"""YandexAIService — ИИ через Yandex AI Studio (ADR-0017).

OpenAI-совместимый Chat Completions API по HTTPS, стандартной библиотекой (urllib).
Ключ и каталог приходят из переменных окружения сервера и никуда не записываются.
Ответ ИИ — один объект JSON; он проверяется Pydantic-схемой, иначе — AIError.
Адаптер ничего не решает и не хранит: решает и записывает CORE.
"""

import hashlib
import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from importlib.resources import files
from string import Template
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ege_tutor.config import AIConfig
from ege_tutor.core.domain import (
    AICriterionScore,
    AIError,
    AIMistakeSuggestion,
    AIPart2Suggestion,
    AITaskContext,
    AITaskSuggestion,
    AIText,
    AIUsage,
    AnswerType,
    Subject,
)

PROMPT_VERSION = "prompts-v1"
_SUBJECT_NAMES = {Subject.MATH_PROFILE: "профильная математика", Subject.INFORMATICS: "информатика"}
_ERROR_BODY_CHARS = 200

Opener = Callable[[urllib.request.Request, float], Any]


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


# ── схемы ответов ИИ ────────────────────────────────────────────────────────

ShortText = Annotated[str, Field(min_length=1, max_length=4000)]
LongText = Annotated[str, Field(min_length=1, max_length=12000)]


class _Schema(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Hint(_Schema):
    hint: ShortText


class _Explanation(_Schema):
    explanation: LongText


class _Mistake(_Schema):
    category: Annotated[str, Field(min_length=1, max_length=40)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    explanation: ShortText


class _Criterion(_Schema):
    name: Annotated[str, Field(min_length=1, max_length=300)]
    points: Annotated[int, Field(ge=0, le=10)]
    max_points: Annotated[int, Field(ge=1, le=10)]
    comment: ShortText


class _Part2(_Schema):
    criteria: Annotated[list[_Criterion], Field(min_length=1, max_length=10)]
    summary: ShortText


class _Generated(_Schema):
    statement: LongText
    answer: Annotated[str, Field(min_length=1, max_length=200)]
    solution: LongText
    check: Annotated[str, Field(min_length=1, max_length=8000)]


# ── промпты ─────────────────────────────────────────────────────────────────


def prompt(name: str) -> str:
    return files("ege_tutor.ai").joinpath("prompts", f"{name}.md").read_text(encoding="utf-8")


def _render(name: str, **values: object) -> str:
    return Template(prompt(name)).substitute({k: str(v) for k, v in values.items()})


def task_block(task: AITaskContext, *, with_answer: bool) -> str:
    """Задача текстом для промпта: только учебные данные, без личных."""
    lines = [
        f"Предмет: {_SUBJECT_NAMES[task.subject]}, задание ЕГЭ №{task.exam_item}.",
        f"Условие:\n{task.statement}",
    ]
    if task.file_names:
        lines.append(f"К задаче приложены файлы: {', '.join(task.file_names)}.")
    if with_answer and task.answer:
        lines.append(f"Эталонный ответ: {task.answer}")
    if with_answer and task.solution:
        lines.append(f"Эталонное решение:\n{task.solution}")
    return "\n".join(lines)


def _answer_format(task: AITaskContext) -> str:
    if task.answer_type == AnswerType.NUMBER:
        return "одно число (целое или конечная десятичная дробь)"
    if task.answer_type == AnswerType.SEQUENCE:
        return "несколько чисел через пробел, как в образце"
    return "строка без пробелов, как в образце"


def _check_rule(task: AITaskContext) -> tuple[str, str]:
    if task.subject == Subject.INFORMATICS:
        return (
            "В поле check напиши программу на Python 3 без ввода и без файлов, которая "
            "вычисляет ответ и печатает его последней строкой. Программа будет запущена.",
            "программа на Python",
        )
    return (
        "В поле check напиши одно арифметическое выражение из чисел (можно sqrt, ^, дроби), "
        "значение которого равно ответу: им ответ будет перепроверен.",
        "выражение",
    )


# ── разбор ответа API ───────────────────────────────────────────────────────


def _json_object(content: str) -> dict[str, Any]:
    """Первый объект JSON в тексте модели (модель иногда оборачивает его в ```)."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("в ответе нет объекта JSON")
    data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("ответ — не объект JSON")
    return data


def _tokens(reported: object, text: str) -> int:
    """Токены из ответа API; если их нет — оценка с запасом: ~2 символа на токен."""
    if isinstance(reported, int) and reported >= 0:
        return reported
    if isinstance(reported, str) and reported.isdigit():  # API Яндекса иногда пишет числа строкой
        return int(reported)
    return math.ceil(len(text) / 2)


class YandexAIService:
    def __init__(
        self,
        config: AIConfig,
        api_key: str,
        folder_id: str,
        *,
        base_url: str | None = None,
        opener: Opener | None = None,
    ) -> None:
        if not api_key or not folder_id:
            raise ValueError("нужны ключ API и идентификатор каталога")
        self._config = config
        self._api_key = api_key
        self._folder_id = folder_id
        self._url = (base_url or config.base_url).rstrip("/") + "/chat/completions"
        self._open = opener or _default_opener

    def __repr__(self) -> str:  # ключ не должен попасть в логи даже случайно
        return f"YandexAIService(model={self.model!r})"

    @property
    def is_available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    @property
    def provider(self) -> str:
        return "yandex"

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def _model_uri(self) -> str:
        model = self._config.model
        return model if model.startswith("gpt://") else f"gpt://{self._folder_id}/{model}"

    # ── транспорт ───────────────────────────────────────────────────────────

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {self._api_key}",
                "OpenAI-Project": self._folder_id,
                # запрет логирования запросов на стороне Яндекса
                "x-data-logging-enabled": "false",
            },
        )
        try:
            with self._open(request, self._config.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise AIError(self._http_error(e)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise AIError("нет связи с Yandex AI Studio. Попробуй позже") from None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AIError("Yandex AI Studio вернул не JSON") from None
        if not isinstance(data, dict):
            raise AIError("Yandex AI Studio вернул неожиданный ответ")
        return data

    @staticmethod
    def _http_error(error: urllib.error.HTTPError) -> str:
        if error.code in (401, 403):
            return (
                "Yandex AI Studio не принял ключ: проверь EGE_YANDEX_API_KEY, "
                "EGE_YANDEX_FOLDER_ID и роль ai.languageModels.user у сервисного аккаунта"
            )
        if error.code == 429:
            return "слишком много запросов к Yandex AI Studio. Подожди минуту"
        detail = ""
        try:
            body = json.loads(error.read() or b"{}")
            message = body.get("error", {}).get("message") if isinstance(body, dict) else None
            if isinstance(message, str):
                detail = ": " + message[:_ERROR_BODY_CHARS]
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, OSError):
            pass
        return f"Yandex AI Studio ответил ошибкой {error.code}{detail}"

    def _ask[S: BaseModel](self, user_prompt: str, schema: type[S]) -> tuple[S, AIUsage]:
        system = prompt("system")
        request_hash = hashlib.sha256(
            f"{PROMPT_VERSION}\n{self.model}\n{system}\n{user_prompt}".encode()
        ).hexdigest()[:16]
        data = self._post(
            {
                "model": self._model_uri,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": self._config.max_output_tokens,
                "temperature": self._config.temperature,
            }
        )
        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, IndexError, TypeError):
            content = ""
        counts = data.get("usage")
        counts = counts if isinstance(counts, dict) else {}
        usage = AIUsage(
            model=self.model,
            input_tokens=_tokens(counts.get("prompt_tokens"), system + user_prompt),
            output_tokens=_tokens(counts.get("completion_tokens"), content),
            request_hash=request_hash,
        )
        if not content:
            raise AIError("ИИ вернул пустой ответ", usage)
        try:
            return schema.model_validate(_json_object(content)), usage
        except (ValueError, ValidationError):
            raise AIError("ИИ ответил не по формату. Попробуй ещё раз", usage) from None

    # ── методы порта ────────────────────────────────────────────────────────

    def hint(self, task: AITaskContext, level: int, previous: Sequence[str]) -> AIText:
        shown = "\n".join(f"- {text}" for text in previous) or "нет"
        user = _render(
            "hint", level=level, task=task_block(task, with_answer=False), previous=shown
        )
        parsed, usage = self._ask(user, _Hint)
        return AIText(parsed.hint.strip(), usage)

    def explain(self, task: AITaskContext, student_answer: str | None) -> AIText:
        user = _render(
            "explain",
            task=task_block(task, with_answer=True),
            student_answer=student_answer or "нет (ученик сдался)",
        )
        parsed, usage = self._ask(user, _Explanation)
        return AIText(parsed.explanation.strip(), usage)

    def classify_mistake(
        self,
        task: AITaskContext,
        student_answer: str | None,
        categories: Sequence[str],
        program_output: str | None,
    ) -> AIMistakeSuggestion:
        user = _render(
            "mistake",
            categories="\n".join(categories),
            task=task_block(task, with_answer=True),
            student_answer=student_answer or "нет (ученик сдался)",
            program_output=(program_output or "нет")[:2000],
        )
        parsed, usage = self._ask(user, _Mistake)
        return AIMistakeSuggestion(
            parsed.category.strip().upper(), parsed.confidence, parsed.explanation.strip(), usage
        )

    def grade_part2(
        self, task: AITaskContext, solution_text: str, max_points: int
    ) -> AIPart2Suggestion:
        user = _render(
            "part2",
            max_points=max_points,
            task=task_block(task, with_answer=True),
            solution_text=solution_text,
        )
        parsed, usage = self._ask(user, _Part2)
        criteria = tuple(
            AICriterionScore(c.name.strip(), c.points, c.max_points, c.comment.strip())
            for c in parsed.criteria
        )
        return AIPart2Suggestion(criteria, parsed.summary.strip(), usage)

    def generate_similar(self, task: AITaskContext) -> AITaskSuggestion:
        rule, check_name = _check_rule(task)
        user = _render(
            "generate",
            answer_format=_answer_format(task),
            task=task_block(task, with_answer=True),
            check_rule=rule,
            check_name=check_name,
        )
        parsed, usage = self._ask(user, _Generated)
        return AITaskSuggestion(
            parsed.statement.strip(),
            parsed.answer.strip(),
            parsed.solution.strip(),
            parsed.check.strip(),
            usage,
        )
