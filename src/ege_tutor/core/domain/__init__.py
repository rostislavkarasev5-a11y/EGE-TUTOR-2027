"""Словарь предметной области: перечисления и сущности."""

from ege_tutor.core.domain.attempt import (
    AnswerCheck,
    Attempt,
    AttemptMode,
    AttemptStatus,
    HintEvent,
    Verdict,
)
from ege_tutor.core.domain.catalog import AnswerKind, Catalog, ExamSpec, ExamSpecItem, Skill, Topic
from ege_tutor.core.domain.content import TaskSource, VerificationStatus
from ege_tutor.core.domain.imports import (
    ImportBatch,
    ImportBatchStatus,
    ImportIssue,
    ImportReport,
)
from ege_tutor.core.domain.profile import DEFAULT_TARGET_SCORE, StudentProfile
from ege_tutor.core.domain.subject import Subject
from ege_tutor.core.domain.task import (
    HINT_LEVELS,
    PRACTICE_STATUSES,
    SOURCE_LABELS,
    AnswerType,
    Task,
    TaskAsset,
    TaskDraft,
    TaskHint,
)

__all__ = [
    "DEFAULT_TARGET_SCORE",
    "HINT_LEVELS",
    "PRACTICE_STATUSES",
    "SOURCE_LABELS",
    "AnswerCheck",
    "AnswerKind",
    "AnswerType",
    "Attempt",
    "AttemptMode",
    "AttemptStatus",
    "Catalog",
    "ExamSpec",
    "ExamSpecItem",
    "HintEvent",
    "ImportBatch",
    "ImportBatchStatus",
    "ImportIssue",
    "ImportReport",
    "Skill",
    "StudentProfile",
    "Subject",
    "Task",
    "TaskAsset",
    "TaskDraft",
    "TaskHint",
    "TaskSource",
    "Topic",
    "Verdict",
    "VerificationStatus",
]
