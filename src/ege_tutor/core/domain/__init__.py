"""Словарь предметной области: перечисления и сущности."""

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
from ege_tutor.core.domain.task import SOURCE_LABELS, AnswerType, Task, TaskAsset, TaskDraft

__all__ = [
    "DEFAULT_TARGET_SCORE",
    "SOURCE_LABELS",
    "AnswerKind",
    "AnswerType",
    "Catalog",
    "ExamSpec",
    "ExamSpecItem",
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
    "TaskSource",
    "Topic",
    "VerificationStatus",
]
