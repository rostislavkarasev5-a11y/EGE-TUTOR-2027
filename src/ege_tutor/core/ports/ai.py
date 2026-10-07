from typing import Protocol, runtime_checkable


@runtime_checkable
class AIService(Protocol):
    """Интеллектуальный слой (Claude API — с Phase 6).

    Принцип: ИИ предлагает → CORE принимает решение → CORE записывает результат.
    AIService ничего не хранит и ничего не решает сам. Любая реализация
    заменяема; без неё приложение продолжает работать (офлайн-режим).

    В Exam Mode AIService не вызывается вообще (ADR-0009).

    Методы (explain, hint, classify_mistake, grade_part2, generate_similar,
    review_plan) добавляются в Phase 6 вместе с типами их результатов.
    """

    @property
    def is_available(self) -> bool:
        """Можно ли сейчас обращаться к ИИ."""
        ...
