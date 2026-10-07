"""AI Layer: реализации порта AIService.

Сейчас есть только DisabledAIService (ИИ выключен). Клиент Claude API — Phase 6.
"""

from ege_tutor.ai.disabled import DisabledAIService

__all__ = ["DisabledAIService"]
