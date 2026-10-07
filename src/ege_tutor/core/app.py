"""TutorApp — единая точка входа в CORE для всех интерфейсов (CLI сейчас, Web потом).

Интерфейсы не содержат логики: они вызывают методы TutorApp и показывают результат.
Новые возможности добавляются сюда по фазам roadmap.
"""

import datetime as dt
from dataclasses import dataclass, replace
from pathlib import Path

from ege_tutor import __version__
from ege_tutor.ai import DisabledAIService
from ege_tutor.config import Settings, load_settings
from ege_tutor.core.clock import SystemClock
from ege_tutor.core.domain import (
    Catalog,
    ExamSpec,
    ImportBatch,
    ImportReport,
    StudentProfile,
    Subject,
    Task,
    TaskAsset,
    TaskSource,
    Topic,
)
from ege_tutor.core.ports import AIService, Clock, Repository, RepositoryError, Sandbox
from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.core.services.content_import import build_report
from ege_tutor.sandbox import UnavailableSandbox

CURRENT_PHASE = 1
DB_FILE_NAME = "ege.db"


class AppError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""


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
    task_count: int


@dataclass(frozen=True)
class ImportResult:
    report: ImportReport
    batch: ImportBatch | None  # None — нечего записывать или это был предпросмотр


class TutorApp:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        ai: AIService,
        sandbox: Sandbox,
        repository: Repository,
        catalog: Catalog,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.ai = ai
        self.sandbox = sandbox
        self.repository = repository
        self.catalog = catalog

    @classmethod
    def create(
        cls,
        settings: Settings | None = None,
        clock: Clock | None = None,
        repository: Repository | None = None,
    ) -> "TutorApp":
        """Собрать приложение с реализациями по умолчанию для текущей фазы.

        Открывает локальную базу (создаёт и обновляет схему при необходимости)
        и синхронизирует каталог тем из content/.
        """
        from ege_tutor.db.repository import SqlRepository  # адаптер подключается только здесь

        settings = settings or load_settings()
        catalog = load_catalog(settings.content_dir)
        if repository is None:
            repository = SqlRepository.open(settings.data_dir / DB_FILE_NAME)
        repository.sync_catalog(catalog)
        return cls(
            settings=settings,
            clock=clock or SystemClock(),
            ai=DisabledAIService(),
            sandbox=UnavailableSandbox(),
            repository=repository,
            catalog=catalog,
        )

    def close(self) -> None:
        self.repository.close()

    # ── состояние ───────────────────────────────────────────────────────────

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
            storage_ready=self.repository.is_ready(),
            ai_available=self.ai.is_available,
            sandbox_available=self.sandbox.is_available,
            task_count=self.repository.count_tasks(),
        )

    # ── профиль ─────────────────────────────────────────────────────────────

    def profile(self) -> StudentProfile:
        return self.repository.get_profile()

    def update_profile(
        self,
        display_name: str | None = None,
        targets: dict[Subject, int] | None = None,
    ) -> StudentProfile:
        current = self.repository.get_profile()
        new_targets = dict(current.targets)
        for subject, score in (targets or {}).items():
            if not 0 <= score <= 100:
                raise AppError(f"цель по предмету должна быть от 0 до 100, получено {score}")
            new_targets[subject] = score
        name = current.display_name if display_name is None else display_name.strip() or None
        if name is not None and len(name) > 100:
            raise AppError("имя не длиннее 100 символов")
        profile = replace(current, display_name=name, targets=new_targets)
        self.repository.save_profile(profile)
        return profile

    # ── каталог ─────────────────────────────────────────────────────────────

    def exam_spec(self, subject: Subject) -> ExamSpec:
        spec = self.repository.get_exam_spec(subject)
        if spec is None:
            raise AppError("структура экзамена не загружена")
        return spec

    def topics(self, subject: Subject) -> list[Topic]:
        return self.repository.list_topics(subject)

    # ── импорт задач ────────────────────────────────────────────────────────

    def _skill_items(self, subject: Subject) -> dict[str, tuple[int, ...]]:
        return {
            skill.code: skill.exam_items
            for topic in self.catalog.topics_of(subject)
            for skill in topic.skills
        }

    def preview_import(self, path: Path) -> ImportReport:
        """Проверить файл с задачами, ничего не записывая."""
        return build_report(
            path,
            specs=self.catalog.specs,
            skill_items=self._skill_items,
            existing_hashes=self.repository.active_task_hashes,
        )

    @property
    def asset_root(self) -> Path:
        """Папка, где лежат файлы к задачам (вне Git)."""
        return self.settings.data_dir / "private_content" / "assets"

    def import_tasks(self, path: Path) -> ImportResult:
        """Записать задачи без ошибок одной пачкой. Ошибочные остаются в отчёте."""
        report = self.preview_import(path)
        if report.file_error or not report.accepted:
            return ImportResult(report, None)
        batch = self.repository.add_import_batch(
            file_name=report.file_name,
            file_format=report.file_format,
            drafts=report.accepted,
            asset_root=self.asset_root,
            rejected_count=len(report.rejected_rows),
            report=report.to_dict(),
            created_at=self.clock.now(),
        )
        return ImportResult(report, batch)

    def import_batches(self) -> list[ImportBatch]:
        return self.repository.list_import_batches()

    def rollback_import(self, batch_id: int) -> ImportBatch:
        try:
            return self.repository.rollback_import_batch(batch_id, self.clock.now())
        except RepositoryError as e:
            raise AppError(str(e)) from e

    # ── задачи ──────────────────────────────────────────────────────────────

    def tasks(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        source: TaskSource | None = None,
        limit: int = 50,
    ) -> list[Task]:
        return self.repository.list_tasks(subject, exam_item, source, limit)

    def task(self, task_id: int) -> Task:
        task = self.repository.get_task(task_id)
        if task is None:
            raise AppError(f"задача №{task_id} не найдена")
        return task

    def asset_path(self, asset: TaskAsset) -> Path:
        """Где на диске лежит файл задачи."""
        return self.asset_root / asset.stored_path
