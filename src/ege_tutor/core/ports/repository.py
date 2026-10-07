import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ege_tutor.core.domain import (
    Catalog,
    ExamSpec,
    ImportBatch,
    StudentProfile,
    Subject,
    Task,
    TaskDraft,
    TaskSource,
    Topic,
)


class RepositoryError(Exception):
    """Операция с хранилищем невозможна (например, повторный откат импорта)."""


@runtime_checkable
class Repository(Protocol):
    """Хранилище данных приложения (реализация — SQLite через SQLAlchemy 2 + Alembic).

    CORE читает и пишет данные только через этот порт. Методы добавляются по фазам.

    Инварианты, которые обязана соблюдать любая реализация:
    - сырые попытки пользователя никогда не удаляются из истории;
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
