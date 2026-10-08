from collections.abc import Sequence

from ege_tutor.core.domain import (
    AIChatReply,
    AIError,
    AIMistakeSuggestion,
    AIPart2Suggestion,
    AITaskContext,
    AITaskSuggestion,
    AIText,
    ChatTurn,
)

DEFAULT_REASON = "ИИ выключен в настройках"


class DisabledAIService:
    """ИИ выключен: приложение работает без ИИ (офлайн-режим).

    Используется, когда provider = "disabled" или на сервере нет ключа.
    Любой вызов — AIError с понятной причиной; CORE до вызова обычно не доходит.
    """

    def __init__(self, reason: str = DEFAULT_REASON, provider: str = "disabled") -> None:
        self._reason = reason
        self._provider = provider

    @property
    def is_available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return "—"

    def _refuse(self) -> AIError:
        return AIError(self._reason)

    def hint(self, task: AITaskContext, level: int, previous: Sequence[str]) -> AIText:
        raise self._refuse()

    def explain(self, task: AITaskContext, student_answer: str | None) -> AIText:
        raise self._refuse()

    def classify_mistake(
        self,
        task: AITaskContext,
        student_answer: str | None,
        categories: Sequence[str],
        program_output: str | None,
    ) -> AIMistakeSuggestion:
        raise self._refuse()

    def grade_part2(
        self, task: AITaskContext, solution_text: str, max_points: int
    ) -> AIPart2Suggestion:
        raise self._refuse()

    def generate_similar(self, task: AITaskContext) -> AITaskSuggestion:
        raise self._refuse()

    def chat(
        self,
        task: AITaskContext,
        history: Sequence[ChatTurn],
        question: str,
        *,
        finished: bool,
    ) -> AIChatReply:
        raise self._refuse()
