"""Порты CORE — интерфейсы к внешнему миру.

CORE зависит только от этих протоколов, а не от конкретных реализаций
(SQLite, Claude API, Docker, системное время). Поэтому реализации можно
заменять, а CORE — тестировать без интернета, без ИИ и без ожидания.
"""

from ege_tutor.core.ports.ai import AIService
from ege_tutor.core.ports.clock import Clock
from ege_tutor.core.ports.repository import Repository
from ege_tutor.core.ports.sandbox import (
    RunRequest,
    RunResult,
    Sandbox,
    SandboxLimits,
    SandboxUnavailableError,
    SandboxVerdict,
)

__all__ = [
    "AIService",
    "Clock",
    "Repository",
    "RunRequest",
    "RunResult",
    "Sandbox",
    "SandboxLimits",
    "SandboxUnavailableError",
    "SandboxVerdict",
]
