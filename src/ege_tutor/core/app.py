"""TutorApp — единая точка входа в CORE для всех интерфейсов (CLI сейчас, Web потом).

Интерфейсы не содержат логики: они вызывают методы TutorApp и показывают результат.
Новые возможности добавляются сюда по фазам roadmap.
"""

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass, replace
from pathlib import Path

from ege_tutor import __version__
from ege_tutor.ai import DisabledAIService
from ege_tutor.config import Settings, load_settings
from ege_tutor.core.clock import SystemClock
from ege_tutor.core.domain import (
    Attempt,
    AttemptMode,
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
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import AIService, Clock, Repository, RepositoryError, Sandbox
from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.core.services.content_import import build_report
from ege_tutor.core.services.practice import AttemptResult, PracticeService, ShownHint
from ege_tutor.sandbox import UnavailableSandbox
from ege_tutor.subjects import tutor_for

CURRENT_PHASE = 2
DB_FILE_NAME = "ege.db"
BACKUP_PREFIX = "ege-"
DEFAULT_BACKUPS_KEPT = 14


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
        self.practice = PracticeService(
            repository, clock, settings.mastery, tutor_for, self._time_norm
        )

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

    # ── резервные копии ─────────────────────────────────────────────────────

    @property
    def backup_dir(self) -> Path:
        return self.settings.data_dir / "backups"

    def backup(self, dest_dir: Path | None = None, keep: int = DEFAULT_BACKUPS_KEPT) -> Path:
        """Сделать копию базы (с проверкой целостности) и оставить только keep последних."""
        if keep < 1:
            raise AppError("нужно хранить хотя бы одну копию")
        folder = dest_dir or self.backup_dir
        stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
        dest = folder / f"{BACKUP_PREFIX}{stamp}.db"
        suffix = 1
        while dest.exists():
            dest = folder / f"{BACKUP_PREFIX}{stamp}-{suffix}.db"
            suffix += 1
        try:
            self.repository.backup_to(dest)
        except RepositoryError as e:
            raise AppError(str(e)) from e
        copies = sorted(
            folder.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: (p.stat().st_mtime, p.name)
        )
        for old in copies[:-keep]:
            old.unlink()
        return dest

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

    # ── решение задач (Phase 2) ─────────────────────────────────────────────

    def _time_norm(self, subject: Subject, exam_item: int) -> int | None:
        spec = self.catalog.specs.get(subject)
        item = spec.item(exam_item) if spec else None
        return item.time_norm_seconds if item else None

    def next_task(self, subject: Subject | None = None, exam_item: int | None = None) -> Task:
        """Какую задачу решать: проверенную, которую решали реже и давнее всего."""
        return self.practice.next_task(subject, exam_item)

    def similar_task(self, task_id: int) -> Task | None:
        return self.practice.similar_task(task_id)

    def start_attempt(self, task_id: int, mode: AttemptMode = AttemptMode.PRACTICE) -> Attempt:
        return self.practice.start(task_id, mode)

    def next_hint(self, attempt_id: int) -> ShownHint:
        return self.practice.next_hint(attempt_id)

    def submit_answer(self, attempt_id: int, answer: str) -> AttemptResult:
        return self.practice.submit(attempt_id, answer)

    def give_up(self, attempt_id: int) -> Attempt:
        return self.practice.give_up(attempt_id)

    def abandon_attempt(self, attempt_id: int) -> Attempt:
        return self.practice.abandon(attempt_id)

    def attempt(self, attempt_id: int) -> Attempt:
        attempt = self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        return attempt

    def shown_hints(self, attempt_id: int) -> list[ShownHint]:
        return self.practice.shown_hints(attempt_id)

    def attempts(self, task_id: int | None = None, limit: int = 50) -> list[Attempt]:
        return self.repository.list_attempts(task_id, limit)

    def review_task(self, task_id: int, answer_is_correct: bool) -> Task:
        return self.practice.review(task_id, answer_is_correct)

    def next_unverified_task(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        exclude: Collection[int] = (),
    ) -> Task | None:
        return self.practice.next_unverified(subject, exam_item, exclude)

    def why_not_practicable(self, task: Task) -> str | None:
        """Почему задачу нельзя решать, или None, если можно."""
        return self.practice.why_not_practicable(task)
