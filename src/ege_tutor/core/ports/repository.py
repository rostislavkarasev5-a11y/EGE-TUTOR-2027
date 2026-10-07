import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ege_tutor.core.domain import (
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    ExamSpec,
    HintEvent,
    ImportBatch,
    StudentProfile,
    Subject,
    Task,
    TaskDraft,
    TaskSource,
    Topic,
    Verdict,
    VerificationStatus,
)


class RepositoryError(Exception):
    """Операция с хранилищем невозможна (например, повторный откат импорта)."""


@runtime_checkable
class Repository(Protocol):
    """Хранилище данных приложения (реализация — SQLite через SQLAlchemy 2 + Alembic).

    CORE читает и пишет данные только через этот порт. Методы добавляются по фазам.

    Инварианты, которые обязана соблюдать любая реализация:
    - сырые попытки пользователя никогда не удаляются из истории (нет метода удаления);
    - снимки mastery и прогнозов не переписываются задним числом;
    - задача не сохраняется без source, source_ref и verification_status;
    - откат импорта не удаляет записи, а выводит задачи из оборота (история сохраняется).
    """

    def is_ready(self) -> bool:
        """Хранилище инициализировано и готово к работе."""
        ...

    def close(self) -> None:
        """Освободить файлы и соединения."""
        ...

    # ── профиль ──
    def get_profile(self) -> StudentProfile: ...

    def save_profile(self, profile: StudentProfile) -> None: ...

    # ── каталог ──
    def sync_catalog(self, catalog: Catalog) -> None:
        """Записать структуру экзаменов, темы и навыки (идемпотентно)."""
        ...

    def list_topics(self, subject: Subject) -> list[Topic]: ...

    def get_exam_spec(self, subject: Subject) -> ExamSpec | None: ...

    # ── задачи и импорт ──
    def active_task_hashes(self, hashes: Iterable[str]) -> set[str]:
        """Какие из хэшей уже есть среди действующих задач."""
        ...

    def add_import_batch(
        self,
        *,
        file_name: str,
        file_format: str,
        drafts: Sequence[TaskDraft],
        asset_root: Path,
        rejected_count: int,
        report: dict,
        created_at: dt.datetime,
    ) -> ImportBatch:
        """Сохранить пачку задач одной транзакцией. Файлы задач копируются в хранилище."""
        ...

    def list_import_batches(self) -> list[ImportBatch]: ...

    def rollback_import_batch(self, batch_id: int, at: dt.datetime) -> ImportBatch:
        """Вывести задачи пачки из оборота. Повторный откат — ошибка."""
        ...

    def list_tasks(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        source: TaskSource | None = None,
        limit: int = 50,
    ) -> list[Task]: ...

    def count_tasks(self) -> int:
        """Сколько действующих задач в базе."""
        ...

    def get_task(self, task_id: int) -> Task | None: ...

    def set_verification_status(
        self, task_id: int, status: VerificationStatus, at: dt.datetime
    ) -> Task: ...

    # ── попытки (Phase 2) ──
    def create_attempt(
        self,
        *,
        task_id: int,
        mode: AttemptMode,
        attempt_no: int,
        started_at: dt.datetime,
        max_hint_level: int,
        time_norm_seconds: int | None,
    ) -> Attempt: ...

    def get_attempt(self, attempt_id: int) -> Attempt | None: ...

    def last_finished_attempt(self, task_id: int) -> Attempt | None: ...

    def count_attempts(self, task_id: int, statuses: Iterable[AttemptStatus]) -> int: ...

    def attempt_stats(self, task_ids: Iterable[int]) -> dict[int, tuple[int, dt.datetime]]:
        """Сколько раз задачу решали (с ответом или сдавшись) и когда последний раз."""
        ...

    def record_hint(self, attempt_id: int, level: int, at: dt.datetime) -> Attempt:
        """Записать показ подсказки и поднять максимальный уровень попытки."""
        ...

    def finish_attempt(
        self,
        attempt_id: int,
        *,
        status: AttemptStatus,
        at: dt.datetime,
        answer: str | None = None,
        answer_normalized: str | None = None,
        verdict: Verdict | None = None,
    ) -> Attempt: ...

    def abandon_in_progress(self, at: dt.datetime) -> int: ...

    def list_attempts(self, task_id: int | None = None, limit: int = 50) -> list[Attempt]: ...

    def list_hint_events(self, attempt_id: int) -> list[HintEvent]: ...
