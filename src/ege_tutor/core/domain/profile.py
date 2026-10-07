from dataclasses import dataclass, field

from ege_tutor.core.domain.subject import Subject

DEFAULT_TARGET_SCORE = 90


def _default_targets() -> dict[Subject, int]:
    return dict.fromkeys(Subject, DEFAULT_TARGET_SCORE)


@dataclass(frozen=True)
class StudentProfile:
    """Профиль ученика. Хранится только в локальной базе, не в Git (ADR-0004)."""

    display_name: str | None = None
    targets: dict[Subject, int] = field(default_factory=_default_targets)
