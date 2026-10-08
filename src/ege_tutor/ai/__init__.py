"""AI Layer: реализации порта AIService (ADR-0017).

- DisabledAIService — ИИ выключен (по умолчанию, офлайн-режим);
- YandexAIService — Yandex AI Studio, включается на сервере ключом в переменных окружения.
"""

import os
from collections.abc import Mapping

from ege_tutor.ai.disabled import DisabledAIService
from ege_tutor.ai.yandex import YandexAIService
from ege_tutor.config import AIConfig
from ege_tutor.core.ports import AIService

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


__all__ = ["API_KEY_ENV", "FOLDER_ENV", "DisabledAIService", "YandexAIService", "make_ai"]
