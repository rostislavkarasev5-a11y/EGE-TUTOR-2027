"""Задача и её метаданные (ADR-0007)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ege_tutor.core.domain.content import TaskSource, VerificationStatus
from ege_tutor.core.domain.subject import Subject


class AnswerType(StrEnum):
    NUMBER = "NUMBER"  # одно число: «6», «-0.5»
    TEXT = "TEXT"  # строка: «ABCD»
    SEQUENCE = "SEQUENCE"  # несколько значений через пробел: «12 3456»
    EXTENDED = "EXTENDED"  # развёрнутое решение; итоговый ответ необязателен


SOURCE_LABELS: dict[TaskSource, str] = {
    TaskSource.OFFICIAL_FIPI: "Официальное задание ФИПИ",
    TaskSource.OPEN_BANK: "Открытый банк заданий",
    TaskSource.USER_MATERIAL: "Материал пользователя",
    TaskSource.AI_GENERATED: "Сгенерировано ИИ — не задание ФИПИ",
}


@dataclass(frozen=True)
class TaskAsset:
    file_name: str
    stored_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class TaskDraft:
    """Задача, прошедшая проверку импорта, но ещё не сохранённая."""

    subject: Subject
    exam_item: int
    statement: str
    answer_type: AnswerType
    answer: str | None
    solution: str | None
    difficulty: int | None
    time_norm_seconds: int | None
    source: TaskSource
    source_ref: str
    source_version: str | None
    verification_status: VerificationStatus
    skills: tuple[str, ...]
    asset_paths: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True)
class Task:
    id: int
    subject: Subject
    exam_item: int
    statement: str
    answer_type: AnswerType
    answer: str | None
    solution: str | None
    difficulty: int | None
    time_norm_seconds: int | None
    source: TaskSource
    source_ref: str
    source_version: str | None
    verification_status: VerificationStatus
    skills: tuple[str, ...]
    assets: tuple[TaskAsset, ...]
    content_hash: str
    import_batch_id: int | None
    created_at: dt.datetime

    @property
    def source_label(self) -> str:
        """Метка источника. Показывается вместе с задачей всегда (ADR-0007)."""
        return SOURCE_LABELS[self.source]
