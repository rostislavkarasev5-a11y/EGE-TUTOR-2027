"""Результаты импорта контента."""

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

from ege_tutor.core.domain.task import TaskDraft


class ImportBatchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True)
class ImportIssue:
    """Проблема в записи. row — номер задачи в файле (с 1) или None для файла целиком."""

    row: int | None
    message: str


@dataclass
class ImportReport:
    file_name: str
    file_format: str
    total: int = 0
    accepted: list[TaskDraft] = field(default_factory=list)
    errors: list[ImportIssue] = field(default_factory=list)
    warnings: list[ImportIssue] = field(default_factory=list)

    @property
    def rejected_rows(self) -> set[int]:
        return {e.row for e in self.errors if e.row is not None}

    @property
    def file_error(self) -> bool:
        return any(e.row is None for e in self.errors)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "file_format": self.file_format,
            "total": self.total,
            "accepted": len(self.accepted),
            "errors": [{"row": e.row, "message": e.message} for e in self.errors],
            "warnings": [{"row": w.row, "message": w.message} for w in self.warnings],
        }


@dataclass(frozen=True)
class ImportBatch:
    id: int
    created_at: dt.datetime
    file_name: str
    file_format: str
    added_count: int
    rejected_count: int
    status: ImportBatchStatus
    rolled_back_at: dt.datetime | None
