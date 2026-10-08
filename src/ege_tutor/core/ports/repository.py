import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ege_tutor.core.domain import (
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    CodeRun,
    CodeVerdict,
    ExamSpec,
    HintEvent,
    ImportBatch,
    MasteryRecord,
    MasterySnapshot,
    Mistake,
    MistakeCategory,
    MistakeDraft,
    MistakePattern,
    Prediction,
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
    - сырые попытки и запуски программ никогда не удаляются из истории (нет метода удаления);
    - снимки mastery и прогнозов за прошлые дни не переписываются задним числом;
    - ошибки не удаляются: уточнение категории — новая запись, старая остаётся в истории;
    - задача не сохраняется без source, source_ref и verification_status;
    - откат импорта не удаляет записи, а выводит задачи из оборота (история сохраняется).
    """

    def is_ready(self) -> bool:
        """Хранилище инициализировано и готово к работе."""
        ...

    def close(self) -> None:
        """Освободить файлы и соединения."""
        ...

    def backup_to(self, dest: Path) -> None:
        """Записать согласованную копию всей базы в файл dest и проверить её целостность."""
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

    # ── запуски программ (Phase 3) ──
    def add_code_run(
        self,
        *,
        task_id: int,
        attempt_id: int | None,
        created_at: dt.datetime,
        code: str,
        verdict: CodeVerdict,
        tests_total: int,
        tests_passed: int,
        failed_test: int | None,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        duration_seconds: float,
    ) -> CodeRun: ...

    def get_code_run(self, run_id: int) -> CodeRun | None: ...

    def list_code_runs(
        self, task_id: int | None = None, attempt_id: int | None = None, limit: int = 20
    ) -> list[CodeRun]:
        """Последние запуски, новые первыми."""
        ...

    # ── mastery, ошибки, повторения (Phase 4) ──
    def skill_history(self, skill_code: str) -> list[tuple[Attempt, int | None]]:
        """Завершённые попытки (ответ или сдался) на задачи с навыком и сложность задачи."""
        ...

    def practiced_skills(self) -> list[str]: ...

    def save_mastery(
        self, records: Sequence[MasteryRecord], snapshots: Sequence[MasterySnapshot]
    ) -> None: ...

    def list_mastery(self, skill_codes: Iterable[str] | None = None) -> list[MasteryRecord]: ...

    def list_snapshots(
        self, skill_code: str | None = None, since: dt.date | None = None
    ) -> list[MasterySnapshot]: ...

    def add_prediction(
        self,
        *,
        attempt_id: int,
        task_id: int,
        model_version: str,
        predicted: float,
        created_at: dt.datetime,
    ) -> Prediction: ...

    def resolve_prediction(self, attempt_id: int, outcome: int, at: dt.datetime) -> None: ...

    def list_predictions(self, limit: int = 1000) -> list[Prediction]: ...

    def add_mistakes(
        self,
        *,
        attempt_id: int,
        task_id: int,
        skill_codes: Sequence[str | None],
        draft: MistakeDraft,
        created_at: dt.datetime,
    ) -> list[Mistake]: ...

    def get_mistake(self, mistake_id: int) -> Mistake | None: ...

    def reclassify_mistake(
        self, mistake_id: int, category: MistakeCategory, description: str, at: dt.datetime
    ) -> Mistake: ...

    def list_mistakes(
        self,
        *,
        skill_code: str | None = None,
        attempt_id: int | None = None,
        current_only: bool = True,
        limit: int = 200,
    ) -> list[Mistake]: ...

    def save_patterns(self, skill_code: str, patterns: Sequence[MistakePattern]) -> None: ...

    def list_patterns(self, open_only: bool = True) -> list[MistakePattern]: ...
