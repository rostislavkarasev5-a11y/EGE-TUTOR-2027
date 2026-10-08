from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ege_tutor.core.domain import (
    AIChatReply,
    AIMistakeSuggestion,
    AIPart2Suggestion,
    AITaskContext,
    AITaskSuggestion,
    AIText,
    ChatTurn,
)


@runtime_checkable
class AIService(Protocol):
    """Интеллектуальный слой (Phase 6, ADR-0017).

    Принцип: ИИ предлагает → CORE принимает решение → CORE записывает результат.
    AIService ничего не хранит и ничего не решает сам: возвращает предложение и расход токенов.
    Любая реализация заменяема; без неё приложение продолжает работать (офлайн-режим).

    В Exam Mode и диагностике AIService не вызывается вообще (ADR-0009, ADR-0016).
    Любой метод при сбое бросает AIError.
    """

    @property
    def is_available(self) -> bool:
        """Можно ли сейчас обращаться к ИИ (настроен ли он)."""
        ...

    @property
    def unavailable_reason(self) -> str | None:
        """Почему ИИ недоступен, понятными словами; None, если доступен."""
        ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def hint(self, task: AITaskContext, level: int, previous: Sequence[str]) -> AIText:
        """Подсказка уровня 1–3, не раскрывающая ответ. previous — уже показанные подсказки."""
        ...

    def explain(self, task: AITaskContext, student_answer: str | None) -> AIText:
        """Объяснение решения после попытки (эталонный ответ уже известен ученику)."""
        ...

    def classify_mistake(
        self,
        task: AITaskContext,
        student_answer: str | None,
        categories: Sequence[str],
        program_output: str | None,
    ) -> AIMistakeSuggestion:
        """К какой категории из списка отнести ошибку и почему."""
        ...

    def grade_part2(
        self, task: AITaskContext, solution_text: str, max_points: int
    ) -> AIPart2Suggestion:
        """Предварительная оценка развёрнутого решения по критериям."""
        ...

    def generate_similar(self, task: AITaskContext) -> AITaskSuggestion:
        """Новая задача того же типа с ответом и способом проверки."""
        ...

    def chat(
        self,
        task: AITaskContext,
        history: Sequence[ChatTurn],
        question: str,
        *,
        finished: bool,
    ) -> AIChatReply:
        """Ответ на вопрос ученика о задаче (ADR-0018).

        finished=False — попытка идёт: ответа задачи в запросе нет, и ИИ его не называет.
        finished=True — попытка закончена: можно разбирать решение и ответ.
        """
        ...
