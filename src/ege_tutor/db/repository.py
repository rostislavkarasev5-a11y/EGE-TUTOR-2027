"""Реализация порта Repository на SQLite (SQLAlchemy 2)."""

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from ege_tutor.core.domain import (
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    ExamSpec,
    ExamSpecItem,
    HintEvent,
    ImportBatch,
    ImportBatchStatus,
    Skill,
    StudentProfile,
    Subject,
    Task,
    TaskAsset,
    TaskDraft,
    TaskHint,
    TaskSource,
    Topic,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.ports.repository import RepositoryError
from ege_tutor.db.engine import is_migrated, make_engine, upgrade_to_head
from ege_tutor.db.models import (
    AttemptRow,
    ExamSpecItemRow,
    ExamSpecRow,
    HintEventRow,
    ImportBatchRow,
    SkillExamItemRow,
    SkillPrerequisiteRow,
    SkillRow,
    StudentRow,
    StudentTargetRow,
    SubjectRow,
    TaskAssetRow,
    TaskHintRow,
    TaskRow,
    TaskSkillRow,
    TopicRow,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_TASK_LOAD = (
    selectinload(TaskRow.skills),
    selectinload(TaskRow.assets),
    selectinload(TaskRow.hints),
)


class SqlRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def open(cls, db_path: Path) -> "SqlRepository":
        """Открыть базу и довести схему до последней версии."""
        engine = make_engine(db_path)
        upgrade_to_head(engine)
        return cls(engine)

    def close(self) -> None:
        self._engine.dispose()

    def is_ready(self) -> bool:
        return is_migrated(self._engine)

    def backup_to(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._engine.connect() as conn:
            source = conn.connection.driver_connection
            target = sqlite3.connect(dest)
            try:
                source.backup(target)  # встроенный механизм SQLite: копия согласована
                (result,) = target.execute("PRAGMA integrity_check").fetchone()
            finally:
                target.close()
        if result != "ok":
            dest.unlink(missing_ok=True)
            raise RepositoryError(f"копия базы повреждена: {result}")

    # ── профиль ─────────────────────────────────────────────────────────────

    def get_profile(self) -> StudentProfile:
        with self._session() as s:
            student = s.get(StudentRow, 1)
            targets = {row.subject: row.target_score for row in s.scalars(select(StudentTargetRow))}
        default = StudentProfile()
        return StudentProfile(
            display_name=student.display_name if student else None,
            targets={
                subject: targets.get(subject, default.targets[subject]) for subject in Subject
            },
        )

    def save_profile(self, profile: StudentProfile) -> None:
        with self._session.begin() as s:
            self._ensure_subjects(s)
            student = s.get(StudentRow, 1) or StudentRow(id=1)
            student.display_name = profile.display_name
            s.add(student)
            for subject, score in profile.targets.items():
                s.merge(StudentTargetRow(subject=subject, target_score=score))

    # ── каталог ─────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_subjects(s: Session) -> None:
        for subject in Subject:
            s.merge(SubjectRow(code=subject))

    def sync_catalog(self, catalog: Catalog) -> None:
        with self._session.begin() as s:
            self._ensure_subjects(s)
            for spec in catalog.specs.values():
                row = s.scalar(
                    select(ExamSpecRow).where(
                        ExamSpecRow.subject == spec.subject, ExamSpecRow.exam_year == spec.exam_year
                    )
                ) or ExamSpecRow(subject=spec.subject, exam_year=spec.exam_year)
                row.status = spec.status
                row.source = spec.source
                row.duration_minutes = spec.duration_minutes
                row.time_norm_source = spec.time_norm_source
                existing = {item.number: item for item in row.items}
                wanted = {i.number for i in spec.items}
                row.items = [item for item in row.items if item.number in wanted]
                for i in spec.items:
                    item = existing.get(i.number)
                    if item is None:
                        item = ExamSpecItemRow(number=i.number)
                        row.items.append(item)
                    item.title = i.title
                    item.part = i.part
                    item.answer_kind = i.answer_kind
                    item.max_points = i.max_points
                    item.time_norm_seconds = i.time_norm_seconds
                s.add(row)
            s.flush()

            # Темы и навыки обновляются по коду; удалённые из каталога остаются в базе,
            # потому что на них могут ссылаться задачи и история.
            for t_pos, topic in enumerate(catalog.topics):
                s.merge(
                    TopicRow(
                        code=topic.code, subject=topic.subject, title=topic.title, position=t_pos
                    )
                )
                for s_pos, skill in enumerate(topic.skills):
                    s.merge(
                        SkillRow(
                            code=skill.code,
                            topic_code=topic.code,
                            title=skill.title,
                            position=s_pos,
                        )
                    )
            s.flush()
            s.execute(delete(SkillExamItemRow))
            s.execute(delete(SkillPrerequisiteRow))
            for topic in catalog.topics:
                for skill in topic.skills:
                    for item in sorted(set(skill.exam_items)):
                        s.add(SkillExamItemRow(skill_code=skill.code, exam_item=item))
                    for req in skill.requires:
                        s.add(SkillPrerequisiteRow(skill_code=skill.code, requires_code=req))

    def list_topics(self, subject: Subject) -> list[Topic]:
        with self._session() as s:
            topics = s.scalars(
                select(TopicRow)
                .where(TopicRow.subject == subject)
                .order_by(TopicRow.position)
                .options(selectinload(TopicRow.skills))
            ).all()
            items: dict[str, list[int]] = {}
            for row in s.scalars(select(SkillExamItemRow).order_by(SkillExamItemRow.exam_item)):
                items.setdefault(row.skill_code, []).append(row.exam_item)
            reqs: dict[str, list[str]] = {}
            for row in s.scalars(select(SkillPrerequisiteRow)):
                reqs.setdefault(row.skill_code, []).append(row.requires_code)
            result = []
            for t in topics:
                skills = tuple(
                    Skill(
                        code=sk.code,
                        title=sk.title,
                        exam_items=tuple(items.get(sk.code, ())),
                        requires=tuple(sorted(reqs.get(sk.code, ()))),
                    )
                    for sk in t.skills
                )
                topic_items = sorted({i for sk in skills for i in sk.exam_items})
                result.append(Topic(t.code, t.subject, t.title, tuple(topic_items), skills))
            return result

    def get_exam_spec(self, subject: Subject) -> ExamSpec | None:
        with self._session() as s:
            row = s.scalar(
                select(ExamSpecRow)
                .where(ExamSpecRow.subject == subject)
                .order_by(ExamSpecRow.exam_year.desc())
                .options(selectinload(ExamSpecRow.items))
            )
            if row is None:
                return None
            return ExamSpec(
                subject=row.subject,
                exam_year=row.exam_year,
                status=row.status,
                source=row.source,
                duration_minutes=row.duration_minutes,
                items=tuple(
                    ExamSpecItem(
                        i.number, i.title, i.part, i.answer_kind, i.max_points, i.time_norm_seconds
                    )
                    for i in row.items
                ),
                time_norm_source=row.time_norm_source,
            )

    # ── задачи и импорт ─────────────────────────────────────────────────────

    def active_task_hashes(self, hashes: Iterable[str]) -> set[str]:
        wanted = set(hashes)
        if not wanted:
            return set()
        with self._session() as s:
            return set(
                s.scalars(
                    select(TaskRow.content_hash).where(
                        TaskRow.is_active.is_(True), TaskRow.content_hash.in_(wanted)
                    )
                )
            )

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
        copied: list[Path] = []
        try:
            with self._session.begin() as s:
                batch = ImportBatchRow(
                    created_at=created_at,
                    file_name=file_name,
                    file_format=file_format,
                    added_count=len(drafts),
                    rejected_count=rejected_count,
                    status=ImportBatchStatus.ACTIVE,
                    report_json=json.dumps(report, ensure_ascii=False),
                )
                s.add(batch)
                s.flush()
                for d in drafts:
                    task = TaskRow(
                        subject=d.subject,
                        exam_item=d.exam_item,
                        statement=d.statement,
                        answer_type=d.answer_type,
                        answer=d.answer,
                        solution=d.solution,
                        difficulty=d.difficulty,
                        time_norm_seconds=d.time_norm_seconds,
                        source=d.source,
                        source_ref=d.source_ref,
                        source_version=d.source_version,
                        verification_status=d.verification_status,
                        verified_at=created_at
                        if d.verification_status != VerificationStatus.UNVERIFIED
                        else None,
                        content_hash=d.content_hash,
                        import_batch_id=batch.id,
                        is_active=True,
                        created_at=created_at,
                        skills=[TaskSkillRow(skill_code=code) for code in d.skills],
                        hints=[TaskHintRow(level=h.level, text=h.text) for h in d.hints],
                    )
                    for source_path in map(Path, d.asset_paths):
                        stored, is_new = self._store_asset(source_path, asset_root)
                        if is_new:
                            copied.append(stored)
                        task.assets.append(
                            TaskAssetRow(
                                file_name=source_path.name,
                                stored_path=stored.relative_to(asset_root).as_posix(),
                                sha256=_sha256(stored),
                                size_bytes=stored.stat().st_size,
                            )
                        )
                    s.add(task)
                s.flush()
                return self._batch(batch)
        except Exception:
            for path in copied:  # транзакция откатилась — убираем скопированные файлы
                path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _store_asset(source: Path, asset_root: Path) -> tuple[Path, bool]:
        """Скопировать файл в хранилище по его хэшу. Одинаковые файлы хранятся один раз."""
        digest = _sha256(source)
        target = asset_root / digest[:2] / f"{digest}{source.suffix.lower()}"
        if target.exists():
            return target, False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target, True

    @staticmethod
    def _batch(row: ImportBatchRow) -> ImportBatch:
        return ImportBatch(
            id=row.id,
            created_at=row.created_at,
            file_name=row.file_name,
            file_format=row.file_format,
            added_count=row.added_count,
            rejected_count=row.rejected_count,
            status=row.status,
            rolled_back_at=row.rolled_back_at,
        )

    def list_import_batches(self) -> list[ImportBatch]:
        with self._session() as s:
            return [
                self._batch(r)
                for r in s.scalars(select(ImportBatchRow).order_by(ImportBatchRow.id))
            ]

    def rollback_import_batch(self, batch_id: int, at: dt.datetime) -> ImportBatch:
        with self._session.begin() as s:
            batch = s.get(ImportBatchRow, batch_id)
            if batch is None:
                raise RepositoryError(f"импорт №{batch_id} не найден")
            if batch.status == ImportBatchStatus.ROLLED_BACK:
                raise RepositoryError(f"импорт №{batch_id} уже отменён")
            for task in s.scalars(select(TaskRow).where(TaskRow.import_batch_id == batch_id)):
                task.is_active = False
            batch.status = ImportBatchStatus.ROLLED_BACK
            batch.rolled_back_at = at
            s.flush()
            return self._batch(batch)

    @staticmethod
    def _task(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            subject=row.subject,
            exam_item=row.exam_item,
            statement=row.statement,
            answer_type=row.answer_type,
            answer=row.answer,
            solution=row.solution,
            difficulty=row.difficulty,
            time_norm_seconds=row.time_norm_seconds,
            source=row.source,
            source_ref=row.source_ref,
            source_version=row.source_version,
            verification_status=row.verification_status,
            skills=tuple(sorted(sk.skill_code for sk in row.skills)),
            assets=tuple(
                TaskAsset(a.file_name, a.stored_path, a.sha256, a.size_bytes) for a in row.assets
            ),
            content_hash=row.content_hash,
            import_batch_id=row.import_batch_id,
            created_at=row.created_at,
            hints=tuple(TaskHint(h.level, h.text) for h in row.hints),
            verified_at=row.verified_at,
        )

    def list_tasks(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        source: TaskSource | None = None,
        limit: int = 50,
    ) -> list[Task]:
        query = select(TaskRow).where(TaskRow.is_active.is_(True))
        if subject is not None:
            query = query.where(TaskRow.subject == subject)
        if exam_item is not None:
            query = query.where(TaskRow.exam_item == exam_item)
        if source is not None:
            query = query.where(TaskRow.source == source)
        query = query.order_by(TaskRow.subject, TaskRow.exam_item, TaskRow.id).limit(limit)
        with self._session() as s:
            rows = s.scalars(query.options(*_TASK_LOAD)).all()
            return [self._task(r) for r in rows]

    def count_tasks(self) -> int:
        with self._session() as s:
            return s.scalar(select(func.count()).where(TaskRow.is_active.is_(True))) or 0

    def get_task(self, task_id: int) -> Task | None:
        with self._session() as s:
            row = s.get(
                TaskRow,
                task_id,
                options=[*_TASK_LOAD],
            )
            return self._task(row) if row is not None and row.is_active else None

    def set_verification_status(
        self, task_id: int, status: VerificationStatus, at: dt.datetime
    ) -> Task:
        with self._session.begin() as s:
            row = s.get(TaskRow, task_id, options=[*_TASK_LOAD])
            if row is None or not row.is_active:
                raise RepositoryError(f"задача №{task_id} не найдена")
            row.verification_status = status
            row.verified_at = at
            s.flush()
            return self._task(row)

    # ── попытки ─────────────────────────────────────────────────────────────

    @staticmethod
    def _attempt(row: AttemptRow) -> Attempt:
        return Attempt(
            id=row.id,
            task_id=row.task_id,
            subject=row.task.subject,
            exam_item=row.task.exam_item,
            mode=row.mode,
            attempt_no=row.attempt_no,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            answer=row.answer,
            verdict=row.verdict,
            max_hint_level=row.max_hint_level,
            time_norm_seconds=row.time_norm_seconds,
        )

    def create_attempt(
        self,
        *,
        task_id: int,
        mode: AttemptMode,
        attempt_no: int,
        started_at: dt.datetime,
        max_hint_level: int,
        time_norm_seconds: int | None,
    ) -> Attempt:
        with self._session.begin() as s:
            row = AttemptRow(
                task_id=task_id,
                mode=mode,
                attempt_no=attempt_no,
                status=AttemptStatus.IN_PROGRESS,
                started_at=started_at,
                max_hint_level=max_hint_level,
                time_norm_seconds=time_norm_seconds,
            )
            s.add(row)
            s.flush()
            return self._attempt(row)

    def get_attempt(self, attempt_id: int) -> Attempt | None:
        with self._session() as s:
            row = s.get(AttemptRow, attempt_id)
            return self._attempt(row) if row is not None else None

    def last_finished_attempt(self, task_id: int) -> Attempt | None:
        with self._session() as s:
            row = s.scalar(
                select(AttemptRow)
                .where(AttemptRow.task_id == task_id, AttemptRow.finished_at.is_not(None))
                .order_by(AttemptRow.finished_at.desc(), AttemptRow.id.desc())
                .limit(1)
            )
            return self._attempt(row) if row is not None else None

    def count_attempts(self, task_id: int, statuses: Iterable[AttemptStatus]) -> int:
        with self._session() as s:
            return (
                s.scalar(
                    select(func.count()).where(
                        AttemptRow.task_id == task_id, AttemptRow.status.in_(list(statuses))
                    )
                )
                or 0
            )

    def attempt_stats(self, task_ids: Iterable[int]) -> dict[int, tuple[int, dt.datetime]]:
        """Сколько раз задачу решали (с ответом или сдавшись) и когда последний раз."""
        ids = list(task_ids)
        if not ids:
            return {}
        done = [AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP]
        with self._session() as s:
            rows = s.execute(
                select(AttemptRow.task_id, func.count(), func.max(AttemptRow.started_at))
                .where(AttemptRow.task_id.in_(ids), AttemptRow.status.in_(done))
                .group_by(AttemptRow.task_id)
            ).all()
        return {
            task_id: (count, last if last.tzinfo else last.replace(tzinfo=dt.UTC))
            for task_id, count, last in rows
        }

    def record_hint(self, attempt_id: int, level: int, at: dt.datetime) -> Attempt:
        with self._session.begin() as s:
            row = s.get(AttemptRow, attempt_id)
            if row is None or row.status != AttemptStatus.IN_PROGRESS:
                raise RepositoryError(f"попытка №{attempt_id} уже завершена")
            s.add(HintEventRow(attempt_id=attempt_id, level=level, shown_at=at))
            row.max_hint_level = max(row.max_hint_level, level)
            s.flush()
            return self._attempt(row)

    def finish_attempt(
        self,
        attempt_id: int,
        *,
        status: AttemptStatus,
        at: dt.datetime,
        answer: str | None = None,
        answer_normalized: str | None = None,
        verdict: Verdict | None = None,
    ) -> Attempt:
        with self._session.begin() as s:
            row = s.get(AttemptRow, attempt_id)
            if row is None or row.status != AttemptStatus.IN_PROGRESS:
                raise RepositoryError(f"попытка №{attempt_id} уже завершена")
            row.status = status
            row.finished_at = at
            row.answer = answer
            row.answer_normalized = answer_normalized
            row.verdict = verdict
            s.flush()
            return self._attempt(row)

    def abandon_in_progress(self, at: dt.datetime) -> int:
        """Незавершённые попытки (например, программу закрыли) помечаются брошенными."""
        with self._session.begin() as s:
            rows = s.scalars(
                select(AttemptRow).where(AttemptRow.status == AttemptStatus.IN_PROGRESS)
            ).all()
            for row in rows:
                row.status = AttemptStatus.ABANDONED
                row.finished_at = at
            return len(rows)

    def list_attempts(self, task_id: int | None = None, limit: int = 50) -> list[Attempt]:
        query = select(AttemptRow).order_by(AttemptRow.started_at.desc(), AttemptRow.id.desc())
        if task_id is not None:
            query = query.where(AttemptRow.task_id == task_id)
        with self._session() as s:
            return [self._attempt(r) for r in s.scalars(query.limit(limit))]

    def list_hint_events(self, attempt_id: int) -> list[HintEvent]:
        with self._session() as s:
            rows = s.scalars(
                select(HintEventRow)
                .where(HintEventRow.attempt_id == attempt_id)
                .order_by(HintEventRow.id)
            )
            return [HintEvent(r.attempt_id, r.level, r.shown_at) for r in rows]
