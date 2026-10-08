"""AI Layer: реализации порта AIService (ADR-0017).

- DisabledAIService — ИИ выключен (по умолчанию, офлайн-режим);
- YandexAIService — Yandex AI Studio, включается на сервере ключом в переменных окружения;
- YandexSpeechService / DisabledSpeechService — голос репетитора (ADR-0018), тот же ключ.
"""

import os
from collections.abc import Mapping

from ege_tutor.ai.disabled import DisabledAIService
from ege_tutor.ai.speechkit import DisabledSpeechService, YandexSpeechService
from ege_tutor.ai.yandex import YandexAIService
from ege_tutor.config import AIConfig, SpeechConfig
from ege_tutor.core.ports import AIService, SpeechService

API_KEY_ENV = "EGE_YANDEX_API_KEY"
FOLDER_ENV = "EGE_YANDEX_FOLDER_ID"


def make_ai(config: AIConfig, environ: Mapping[str, str] | None = None) -> AIService:
    """ИИ по настройкам. Нет ключа — честно выключен с причиной, приложение работает дальше."""
    env = os.environ if environ is None else environ
    if config.provider == "disabled":
        return DisabledAIService()
    key, folder = env.get(API_KEY_ENV, "").strip(), env.get(FOLDER_ENV, "").strip()
    missing = [name for name, value in ((API_KEY_ENV, key), (FOLDER_ENV, folder)) if not value]
    if missing:
        return DisabledAIService(
            f"ИИ включён, но на сервере не задано: {', '.join(missing)}", provider=config.provider
        )
    return YandexAIService(config, key, folder)


def make_speech(
    config: SpeechConfig, ai_config: AIConfig, environ: Mapping[str, str] | None = None
) -> SpeechService:
    """Голос по настройкам. Работает только вместе с ИИ: общий ключ и общий лимит трат."""
    env = os.environ if environ is None else environ
    if not config.enabled:
        return DisabledSpeechService()
    if ai_config.provider == "disabled":
        return DisabledSpeechService("голос работает вместе с ИИ, а ИИ выключен")
    key = env.get(API_KEY_ENV, "").strip()
    if not key:
        return DisabledSpeechService(f"на сервере не задано: {API_KEY_ENV}")
    return YandexSpeechService(config, key)


__all__ = [
    "API_KEY_ENV",
    "FOLDER_ENV",
    "DisabledAIService",
    "DisabledSpeechService",
    "YandexAIService",
    "YandexSpeechService",
    "make_ai",
    "make_speech",
]
