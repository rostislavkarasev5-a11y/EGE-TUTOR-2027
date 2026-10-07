"""TutorApp — единая точка входа в CORE для всех интерфейсов (CLI сейчас, Web потом).

Интерфейсы не содержат логики: они вызывают методы TutorApp и показывают результат.
Новые возможности добавляются сюда по фазам roadmap.
"""

import datetime as dt
from dataclasses import dataclass

from ege_tutor import __version__
from ege_tutor.ai import DisabledAIService
from ege_tutor.config import Settings, load_settings
from ege_tutor.core.clock import SystemClock
from ege_tutor.core.domain import Subject
from ege_tutor.core.ports import AIService, Clock, Repository, Sandbox
from ege_tutor.sandbox import UnavailableSandbox

CURRENT_PHASE = 0


@dataclass(frozen=True)
class ExamCountdown:
    subject: Subject
    status: str
    date: dt.date | None
    days_left: int | None  # None, пока дата не утверждена официально


@dataclass(frozen=True)
class AppInfo:
    version: str
    phase: int
    exams: tuple[ExamCountdown, ...]
    storage_ready: bool
    ai_available: bool
    sandbox_available: bool


class TutorApp:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        ai: AIService,
        sandbox: Sandbox,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.ai = ai
        self.sandbox = sandbox
        self.repository = repository  # хранилище подключается в Phase 1

    @classmethod
    def create(cls, settings: Settings | None = None, clock: Clock | None = None) -> "TutorApp":
        """Собрать приложение с реализациями по умолчанию для текущей фазы."""
        return cls(
            settings=settings or load_settings(),
            clock=clock or SystemClock(),
            ai=DisabledAIService(),
            sandbox=UnavailableSandbox(),
        )

    def exam_countdown(self, subject: Subject) -> ExamCountdown:
        exam = self.settings.app.exams[subject]
        days_left = None
        if exam.status == "OFFICIAL" and exam.date is not None:
            days_left = (exam.date - self.clock.today()).days
        return ExamCountdown(subject, exam.status, exam.date, days_left)

    def info(self) -> AppInfo:
        return AppInfo(
            version=__version__,
            phase=CURRENT_PHASE,
            exams=tuple(self.exam_countdown(s) for s in Subject),
            storage_ready=self.repository is not None and self.repository.is_ready(),
            ai_available=self.ai.is_available,
            sandbox_available=self.sandbox.is_available,
        )
