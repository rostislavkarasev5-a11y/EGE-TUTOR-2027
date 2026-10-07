class DisabledAIService:
    """ИИ выключен: приложение работает без Claude API.

    Используется по умолчанию до Phase 6 и всегда, когда ИИ отключён в настройках.
    """

    @property
    def is_available(self) -> bool:
        return False
