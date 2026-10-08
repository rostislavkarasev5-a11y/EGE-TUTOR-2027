from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechService(Protocol):
    """Голос репетитора (Phase 6.5, ADR-0018): озвучка и распознавание речи.

    Как и AIService, ничего не хранит и не решает: CORE выбирает, что озвучить,
    кэширует звук, считает траты и проверяет лимит. Любой метод при сбое бросает SpeechError.
    """

    @property
    def is_available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    @property
    def voice(self) -> str:
        """Имя голоса (для учёта трат и ключа кэша)."""
        ...

    def synthesize(self, text: str) -> bytes:
        """Озвучить текст. Возвращает звук в формате MP3."""
        ...

    def recognize(self, pcm: bytes, sample_rate: int) -> str:
        """Распознать речь: 16-битный моно PCM (little-endian) без заголовка."""
        ...
