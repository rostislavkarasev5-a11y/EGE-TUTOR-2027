"""Метаданные учебного контента: источник и статус проверки (ADR-0007)."""

from enum import StrEnum


class TaskSource(StrEnum):
    """Источник задачи. Обязателен для каждой задачи."""

    OFFICIAL_FIPI = "OFFICIAL_FIPI"
    OPEN_BANK = "OPEN_BANK"
    USER_MATERIAL = "USER_MATERIAL"
    AI_GENERATED = "AI_GENERATED"


class VerificationStatus(StrEnum):
    """Статус проверки задачи."""

    UNVERIFIED = "UNVERIFIED"
    AUTO_CHECKED = "AUTO_CHECKED"
    REVIEWED = "REVIEWED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
