"""Реализация порта Repository на SQLite (SQLAlchemy 2)."""

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from ege_tutor.core.domain import (
    AICall,
    AICallStatus,
    AICriterionScore,
    AINote,
    AIPurpose,
    AIUsage,
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    ChatMessage,
    ChatRole,
    ClassifiedBy,
    CodeRun,
    CodeVerdict,
    DiagnosticItemResult,
    DiagnosticSession,
    DiagnosticStatus,
    ExamSpec,
    ExamSpecItem,
    Forecast,
    HintEvent,
    ImportBatch,
    ImportBatchStatus,
    MasteryRecord,
    MasterySnapshot,
    Mistake,
    MistakeCategory,
    MistakeDraft,
    MistakePattern,
    Part2Grade,
    Part2GradeStatus,
    Prediction,
    Skill,
    StopReason,
    StudentProfile,
    Subject,
    Task,
    TaskAsset,
    TaskDraft,
    TaskHint,
    TaskSource,
    TaskTestCase,
    Topic,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.ports.repository import RepositoryError
from ege_tutor.db.engine import is_migrated, make_engine, upgrade_to_head
from ege_tutor.db.models import (
    AICallRow,
    AINoteRow,
    AttemptRow,
    ChatMessageRow,
    CodeRunRow,
    DiagnosticAttemptRow,
    DiagnosticResultRow,
    DiagnosticSessionRow,
    ExamSpecItemRow,
    ExamSpecRow,
    HintEventRow,
    ImportBatchRow,
    MasteryRow,
    MasterySnapshotRow,
    MistakePatternRow,
    MistakeRow,
    Part2GradeRow,
    PredictionRow,
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
    TaskTestCaseRow,
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
    selectinload(TaskRow.tests),
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
                        tests=[
                            TaskTestCaseRow(
                                position=t.position,
                                input=t.input,
                                output=t.output,
                                files_json=json.dumps(dict(t.files), ensure_ascii=False),
                            )
                            for t in d.tests
                        ],
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
            tests=tuple(
                TaskTestCase(t.position, t.input, t.output, tuple(json.loads(t.files_json).items()))
                for t in row.tests
            ),
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

    # ── запуски программ (Phase 3) ──

    @staticmethod
    def _code_run(row: CodeRunRow) -> CodeRun:
        return CodeRun(
            id=row.id,
            task_id=row.task_id,
            attempt_id=row.attempt_id,
            created_at=row.created_at,
            code=row.code,
            verdict=row.verdict,
            tests_total=row.tests_total,
            tests_passed=row.tests_passed,
            failed_test=row.failed_test,
            stdout=row.stdout,
            stderr=row.stderr,
            exit_code=row.exit_code,
            duration_seconds=row.duration_seconds,
        )

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
    ) -> CodeRun:
        with self._session.begin() as s:
            row = CodeRunRow(
                task_id=task_id,
                attempt_id=attempt_id,
                created_at=created_at,
                code=code,
                verdict=verdict,
                tests_total=tests_total,
                tests_passed=tests_passed,
                failed_test=failed_test,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_seconds=duration_seconds,
            )
            s.add(row)
            s.flush()
            return self._code_run(row)

    def get_code_run(self, run_id: int) -> CodeRun | None:
        with self._session() as s:
            row = s.get(CodeRunRow, run_id)
            return self._code_run(row) if row else None

    def list_code_runs(
        self, task_id: int | None = None, attempt_id: int | None = None, limit: int = 20
    ) -> list[CodeRun]:
        query = select(CodeRunRow).order_by(CodeRunRow.created_at.desc(), CodeRunRow.id.desc())
        if task_id is not None:
            query = query.where(CodeRunRow.task_id == task_id)
        if attempt_id is not None:
            query = query.where(CodeRunRow.attempt_id == attempt_id)
        with self._session() as s:
            return [self._code_run(r) for r in s.scalars(query.limit(limit))]

    # ── mastery, ошибки, повторения (Phase 4) ──

    def skill_history(self, skill_code: str) -> list[tuple[Attempt, int | None]]:
        """Завершённые попытки на задачи с навыком (с ответом или сдался) и сложность задачи."""
        query = (
            select(AttemptRow, TaskRow.difficulty)
            .join(TaskRow, TaskRow.id == AttemptRow.task_id)
            .join(TaskSkillRow, TaskSkillRow.task_id == TaskRow.id)
            .where(
                TaskSkillRow.skill_code == skill_code,
                AttemptRow.status.in_([AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP]),
            )
            .order_by(AttemptRow.finished_at, AttemptRow.id)
        )
        with self._session() as s:
            return [(self._attempt(row), difficulty) for row, difficulty in s.execute(query)]

    def practiced_skills(self) -> list[str]:
        """Навыки, по которым есть хотя бы одна завершённая попытка."""
        query = (
            select(TaskSkillRow.skill_code)
            .join(AttemptRow, AttemptRow.task_id == TaskSkillRow.task_id)
            .where(AttemptRow.status.in_([AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP]))
            .distinct()
            .order_by(TaskSkillRow.skill_code)
        )
        with self._session() as s:
            return list(s.scalars(query))

    @staticmethod
    def _mastery(row: MasteryRow) -> MasteryRecord:
        return MasteryRecord(
            skill_code=row.skill_code,
            model_version=row.model_version,
            value_raw=row.value_raw,
            confidence=row.confidence,
            stability_days=row.stability_days,
            attempts=row.attempts,
            last_practiced_at=row.last_practiced_at,
            next_review_on=row.next_review_on,
            updated_at=row.updated_at,
        )

    def save_mastery(
        self, records: Sequence[MasteryRecord], snapshots: Sequence[MasterySnapshot]
    ) -> None:
        """Записать состояния навыков и снимки за день одной транзакцией.

        Снимок за дату перезаписывается только для той же даты; прошлые дни не трогаются,
        потому что вызывающий передаёт только сегодняшние снимки.
        """
        with self._session.begin() as s:
            for r in records:
                row = s.get(MasteryRow, r.skill_code) or MasteryRow(skill_code=r.skill_code)
                row.model_version = r.model_version
                row.value_raw = r.value_raw
                row.confidence = r.confidence
                row.stability_days = r.stability_days
                row.attempts = r.attempts
                row.last_practiced_at = r.last_practiced_at
                row.next_review_on = r.next_review_on
                row.updated_at = r.updated_at
                s.add(row)
            for snap in snapshots:
                key = (snap.snapshot_date, snap.skill_code, snap.model_version)
                row = s.get(MasterySnapshotRow, key) or MasterySnapshotRow(
                    snapshot_date=snap.snapshot_date,
                    skill_code=snap.skill_code,
                    model_version=snap.model_version,
                )
                row.value = snap.value
                row.value_raw = snap.value_raw
                row.confidence = snap.confidence
                s.add(row)

    def list_mastery(self, skill_codes: Iterable[str] | None = None) -> list[MasteryRecord]:
        query = select(MasteryRow).order_by(MasteryRow.skill_code)
        if skill_codes is not None:
            query = query.where(MasteryRow.skill_code.in_(list(skill_codes)))
        with self._session() as s:
            return [self._mastery(r) for r in s.scalars(query)]

    def list_snapshots(
        self, skill_code: str | None = None, since: dt.date | None = None
    ) -> list[MasterySnapshot]:
        query = select(MasterySnapshotRow).order_by(
            MasterySnapshotRow.snapshot_date, MasterySnapshotRow.skill_code
        )
        if skill_code is not None:
            query = query.where(MasterySnapshotRow.skill_code == skill_code)
        if since is not None:
            query = query.where(MasterySnapshotRow.snapshot_date >= since)
        with self._session() as s:
            return [
                MasterySnapshot(
                    r.snapshot_date,
                    r.skill_code,
                    r.model_version,
                    r.value,
                    r.value_raw,
                    r.confidence,
                )
                for r in s.scalars(query)
            ]

    @staticmethod
    def _prediction(row: PredictionRow) -> Prediction:
        return Prediction(
            row.attempt_id, row.model_version, row.predicted, row.outcome, row.created_at
        )

    def add_prediction(
        self,
        *,
        attempt_id: int,
        task_id: int,
        model_version: str,
        predicted: float,
        created_at: dt.datetime,
    ) -> Prediction:
        with self._session.begin() as s:
            row = PredictionRow(
                attempt_id=attempt_id,
                task_id=task_id,
                model_version=model_version,
                predicted=predicted,
                created_at=created_at,
            )
            s.add(row)
            s.flush()
            return self._prediction(row)

    def resolve_prediction(self, attempt_id: int, outcome: int, at: dt.datetime) -> None:
        with self._session.begin() as s:
            s.execute(
                update(PredictionRow)
                .where(PredictionRow.attempt_id == attempt_id, PredictionRow.outcome.is_(None))
                .values(outcome=outcome, resolved_at=at)
            )

    def list_predictions(self, limit: int = 1000) -> list[Prediction]:
        query = select(PredictionRow).order_by(PredictionRow.id.desc()).limit(limit)
        with self._session() as s:
            return [self._prediction(r) for r in s.scalars(query)]

    @staticmethod
    def _mistake(row: MistakeRow) -> Mistake:
        return Mistake(
            id=row.id,
            attempt_id=row.attempt_id,
            task_id=row.task_id,
            skill_code=row.skill_code,
            category=row.category,
            classified_by=row.classified_by,
            confidence=row.confidence,
            description=row.description,
            created_at=row.created_at,
            is_current=row.is_current,
        )

    def add_mistakes(
        self,
        *,
        attempt_id: int,
        task_id: int,
        skill_codes: Sequence[str | None],
        draft: MistakeDraft,
        created_at: dt.datetime,
    ) -> list[Mistake]:
        with self._session.begin() as s:
            rows = [
                MistakeRow(
                    attempt_id=attempt_id,
                    task_id=task_id,
                    skill_code=code,
                    category=draft.category,
                    classified_by=draft.classified_by,
                    confidence=draft.confidence,
                    description=draft.description,
                    created_at=created_at,
                    is_current=True,
                )
                for code in skill_codes
            ]
            s.add_all(rows)
            s.flush()
            return [self._mistake(r) for r in rows]

    def get_mistake(self, mistake_id: int) -> Mistake | None:
        with self._session() as s:
            row = s.get(MistakeRow, mistake_id)
            return self._mistake(row) if row else None

    def reclassify_mistake(
        self, mistake_id: int, category: MistakeCategory, description: str, at: dt.datetime
    ) -> Mistake:
        """Уточнение пользователя: старая запись остаётся в истории, новая становится текущей."""
        with self._session.begin() as s:
            old = s.get(MistakeRow, mistake_id)
            if old is None:
                raise RepositoryError(f"ошибка №{mistake_id} не найдена")
            if not old.is_current:
                raise RepositoryError(f"ошибка №{mistake_id} уже уточнена")
            old.is_current = False
            row = MistakeRow(
                attempt_id=old.attempt_id,
                task_id=old.task_id,
                skill_code=old.skill_code,
                category=category,
                classified_by=ClassifiedBy.USER,
                confidence=1.0,
                description=description,
                created_at=at,
                is_current=True,
                replaces_id=old.id,
            )
            s.add(row)
            s.flush()
            return self._mistake(row)

    def list_mistakes(
        self,
        *,
        skill_code: str | None = None,
        attempt_id: int | None = None,
        current_only: bool = True,
        limit: int = 200,
    ) -> list[Mistake]:
        query = select(MistakeRow).order_by(MistakeRow.created_at.desc(), MistakeRow.id.desc())
        if skill_code is not None:
            query = query.where(MistakeRow.skill_code == skill_code)
        if attempt_id is not None:
            query = query.where(MistakeRow.attempt_id == attempt_id)
        if current_only:
            query = query.where(MistakeRow.is_current.is_(True))
        with self._session() as s:
            return [self._mistake(r) for r in s.scalars(query.limit(limit))]

    def save_patterns(self, skill_code: str, patterns: Sequence[MistakePattern]) -> None:
        """Заменить паттерны навыка пересчитанными (это производные данные)."""
        with self._session.begin() as s:
            s.execute(delete(MistakePatternRow).where(MistakePatternRow.skill_code == skill_code))
            s.add_all(
                MistakePatternRow(
                    skill_code=p.skill_code,
                    category=p.category,
                    occurrences=p.occurrences,
                    first_at=p.first_at,
                    last_at=p.last_at,
                    independent_streak=p.independent_streak,
                    closed_at=p.closed_at,
                    priority=p.priority,
                )
                for p in patterns
            )

    def list_patterns(self, open_only: bool = True) -> list[MistakePattern]:
        query = select(MistakePatternRow).order_by(
            MistakePatternRow.priority.desc(), MistakePatternRow.skill_code
        )
        if open_only:
            query = query.where(MistakePatternRow.closed_at.is_(None))
        with self._session() as s:
            return [
                MistakePattern(
                    r.skill_code,
                    r.category,
                    r.occurrences,
                    r.first_at,
                    r.last_at,
                    r.independent_streak,
                    r.closed_at,
                    r.priority,
                )
                for r in s.scalars(query)
            ]

    # ── диагностика (Phase 5) ───────────────────────────────────────────────

    @staticmethod
    def _diagnostic_session(row: DiagnosticSessionRow) -> DiagnosticSession:
        forecast = None
        if row.forecast_mean is not None:
            assert row.forecast_low is not None and row.forecast_high is not None
            assert row.forecast_max_points is not None and row.forecast_interval is not None
            forecast = Forecast(
                mean=row.forecast_mean,
                low=row.forecast_low,
                high=row.forecast_high,
                max_points=row.forecast_max_points,
                interval=row.forecast_interval,
            )
        return DiagnosticSession(
            id=row.id,
            subject=row.subject,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            stop_reason=row.stop_reason,
            model_version=row.model_version,
            forecast=forecast,
        )

    def create_diagnostic_session(
        self, subject: Subject, model_version: str, started_at: dt.datetime
    ) -> DiagnosticSession:
        with self._session.begin() as s:
            row = DiagnosticSessionRow(
                subject=subject,
                status=DiagnosticStatus.ACTIVE,
                started_at=started_at,
                model_version=model_version,
            )
            s.add(row)
            s.flush()
            return self._diagnostic_session(row)

    def get_diagnostic_session(self, session_id: int) -> DiagnosticSession | None:
        with self._session() as s:
            row = s.get(DiagnosticSessionRow, session_id)
            return self._diagnostic_session(row) if row else None

    def active_diagnostic_session(self, subject: Subject) -> DiagnosticSession | None:
        query = (
            select(DiagnosticSessionRow)
            .where(
                DiagnosticSessionRow.subject == subject,
                DiagnosticSessionRow.status == DiagnosticStatus.ACTIVE,
            )
            .order_by(DiagnosticSessionRow.started_at.desc(), DiagnosticSessionRow.id.desc())
        )
        with self._session() as s:
            row = s.scalars(query).first()
            return self._diagnostic_session(row) if row else None

    def list_diagnostic_sessions(
        self, subject: Subject | None = None, limit: int = 20
    ) -> list[DiagnosticSession]:
        query = select(DiagnosticSessionRow).order_by(
            DiagnosticSessionRow.started_at.desc(), DiagnosticSessionRow.id.desc()
        )
        if subject is not None:
            query = query.where(DiagnosticSessionRow.subject == subject)
        with self._session() as s:
            return [self._diagnostic_session(row) for row in s.scalars(query.limit(limit))]

    def add_diagnostic_attempt(self, session_id: int, attempt_id: int) -> None:
        with self._session.begin() as s:
            s.add(DiagnosticAttemptRow(session_id=session_id, attempt_id=attempt_id))

    def diagnostic_attempts(self, session_id: int) -> list[tuple[Attempt, int | None]]:
        query = (
            select(AttemptRow, TaskRow.difficulty)
            .join(DiagnosticAttemptRow, DiagnosticAttemptRow.attempt_id == AttemptRow.id)
            .join(TaskRow, TaskRow.id == AttemptRow.task_id)
            .where(DiagnosticAttemptRow.session_id == session_id)
            .order_by(AttemptRow.started_at, AttemptRow.id)
        )
        with self._session() as s:
            return [(self._attempt(row), difficulty) for row, difficulty in s.execute(query)]

    def diagnostic_session_of_attempt(self, attempt_id: int) -> int | None:
        with self._session() as s:
            row = s.get(DiagnosticAttemptRow, attempt_id)
            return row.session_id if row else None

    def finish_diagnostic_session(
        self,
        session_id: int,
        *,
        status: DiagnosticStatus,
        at: dt.datetime,
        reason: StopReason | None,
        forecast: Forecast | None,
        results: Sequence[DiagnosticItemResult],
    ) -> DiagnosticSession:
        with self._session.begin() as s:
            row = s.get(DiagnosticSessionRow, session_id)
            if row is None:
                raise RepositoryError(f"диагностика №{session_id} не найдена")
            if row.status != DiagnosticStatus.ACTIVE:
                raise RepositoryError(f"диагностика №{session_id} уже завершена")
            row.status = status
            row.finished_at = at
            row.stop_reason = reason
            if forecast is not None:
                row.forecast_mean = forecast.mean
                row.forecast_low = forecast.low
                row.forecast_high = forecast.high
                row.forecast_max_points = forecast.max_points
                row.forecast_interval = forecast.interval
            for result in results:
                s.add(
                    DiagnosticResultRow(
                        session_id=session_id,
                        exam_item=result.exam_item,
                        probability=result.probability,
                        confidence=result.confidence,
                        basis=result.basis,
                        answered=result.answered,
                    )
                )
            s.flush()
            return self._diagnostic_session(row)

    def diagnostic_results(self, session_id: int) -> list[DiagnosticItemResult]:
        query = (
            select(DiagnosticResultRow)
            .where(DiagnosticResultRow.session_id == session_id)
            .order_by(DiagnosticResultRow.exam_item)
        )
        with self._session() as s:
            return [
                DiagnosticItemResult(
                    exam_item=row.exam_item,
                    probability=row.probability,
                    confidence=row.confidence,
                    basis=row.basis,
                    answered=row.answered,
                )
                for row in s.scalars(query)
            ]

    # ── ИИ (Phase 6) ────────────────────────────────────────────────────────

    @staticmethod
    def _ai_call(row: AICallRow) -> AICall:
        return AICall(
            id=row.id,
            purpose=row.purpose,
            status=row.status,
            model=row.model,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_rub=row.cost_rub,
            request_hash=row.request_hash,
            created_at=row.created_at,
            error=row.error,
            attempt_id=row.attempt_id,
            task_id=row.task_id,
        )

    def add_ai_call(
        self,
        *,
        purpose: AIPurpose,
        status: AICallStatus,
        model: str,
        usage: AIUsage | None,
        cost_rub: float,
        at: dt.datetime,
        error: str | None = None,
        attempt_id: int | None = None,
        task_id: int | None = None,
    ) -> AICall:
        with self._session.begin() as s:
            row = AICallRow(
                purpose=purpose,
                status=status,
                model=model,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cost_rub=cost_rub,
                request_hash=usage.request_hash if usage else "",
                error=error,
                attempt_id=attempt_id,
                task_id=task_id,
                created_at=at,
            )
            s.add(row)
            s.flush()
            return self._ai_call(row)

    def ai_usage_since(self, since: dt.datetime) -> tuple[float, int]:
        query = select(func.coalesce(func.sum(AICallRow.cost_rub), 0.0), func.count()).where(
            AICallRow.created_at >= since
        )
        with self._session() as s:
            cost, count = s.execute(query).one()
            return float(cost), int(count)

    def list_ai_calls(self, limit: int = 50) -> list[AICall]:
        query = select(AICallRow).order_by(AICallRow.created_at.desc(), AICallRow.id.desc())
        with self._session() as s:
            return [self._ai_call(row) for row in s.scalars(query.limit(limit))]

    @staticmethod
    def _ai_note(row: AINoteRow) -> AINote:
        return AINote(
            id=row.id,
            purpose=row.purpose,
            text=row.text,
            created_at=row.created_at,
            attempt_id=row.attempt_id,
            task_id=row.task_id,
            mistake_id=row.mistake_id,
            hint_level=row.hint_level,
            category=row.category,
            confidence=row.confidence,
        )

    def add_ai_note(
        self,
        *,
        ai_call_id: int,
        purpose: AIPurpose,
        text: str,
        at: dt.datetime,
        attempt_id: int | None = None,
        task_id: int | None = None,
        mistake_id: int | None = None,
        hint_level: int | None = None,
        category: MistakeCategory | None = None,
        confidence: float | None = None,
    ) -> AINote:
        with self._session.begin() as s:
            row = AINoteRow(
                ai_call_id=ai_call_id,
                purpose=purpose,
                text=text,
                attempt_id=attempt_id,
                task_id=task_id,
                mistake_id=mistake_id,
                hint_level=hint_level,
                category=category,
                confidence=confidence,
                created_at=at,
            )
            s.add(row)
            s.flush()
            return self._ai_note(row)

    def list_ai_notes(
        self,
        *,
        attempt_id: int | None = None,
        mistake_id: int | None = None,
        purpose: AIPurpose | None = None,
    ) -> list[AINote]:
        query = select(AINoteRow).order_by(AINoteRow.created_at, AINoteRow.id)
        if attempt_id is not None:
            query = query.where(AINoteRow.attempt_id == attempt_id)
        if mistake_id is not None:
            query = query.where(AINoteRow.mistake_id == mistake_id)
        if purpose is not None:
            query = query.where(AINoteRow.purpose == purpose)
        with self._session() as s:
            return [self._ai_note(row) for row in s.scalars(query)]

    def get_ai_note(self, note_id: int) -> AINote | None:
        with self._session() as s:
            row = s.get(AINoteRow, note_id)
            return None if row is None else self._ai_note(row)

    # ── разговор с репетитором (Phase 6.5) ───────────────────────────────────

    @staticmethod
    def _chat_message(row: ChatMessageRow) -> ChatMessage:
        return ChatMessage(
            id=row.id,
            attempt_id=row.attempt_id,
            role=row.role,
            text=row.text,
            created_at=row.created_at,
            speech=row.speech,
            ai_call_id=row.ai_call_id,
        )

    def add_chat_message(
        self,
        *,
        attempt_id: int,
        role: ChatRole,
        text: str,
        at: dt.datetime,
        speech: str | None = None,
        ai_call_id: int | None = None,
    ) -> ChatMessage:
        with self._session.begin() as s:
            row = ChatMessageRow(
                attempt_id=attempt_id,
                role=role,
                text=text,
                speech=speech,
                ai_call_id=ai_call_id,
                created_at=at,
            )
            s.add(row)
            s.flush()
            return self._chat_message(row)

    def list_chat_messages(self, attempt_id: int) -> list[ChatMessage]:
        query = (
            select(ChatMessageRow)
            .where(ChatMessageRow.attempt_id == attempt_id)
            .order_by(ChatMessageRow.created_at, ChatMessageRow.id)
        )
        with self._session() as s:
            return [self._chat_message(row) for row in s.scalars(query)]

    def get_chat_message(self, message_id: int) -> ChatMessage | None:
        with self._session() as s:
            row = s.get(ChatMessageRow, message_id)
            return None if row is None else self._chat_message(row)

    @staticmethod
    def _part2_grade(row: Part2GradeRow) -> Part2Grade:
        criteria = tuple(AICriterionScore(**c) for c in json.loads(row.criteria_json))
        return Part2Grade(
            id=row.id,
            task_id=row.task_id,
            solution_text=row.solution_text,
            points=row.points,
            max_points=row.max_points,
            criteria=criteria,
            summary=row.summary,
            status=row.status,
            created_at=row.created_at,
            attempt_id=row.attempt_id,
        )

    def add_part2_grade(
        self,
        *,
        task_id: int,
        solution_text: str,
        points: int,
        max_points: int,
        criteria: Sequence[AICriterionScore],
        summary: str,
        status: Part2GradeStatus,
        at: dt.datetime,
        ai_call_id: int | None = None,
        attempt_id: int | None = None,
    ) -> Part2Grade:
        with self._session.begin() as s:
            row = Part2GradeRow(
                task_id=task_id,
                attempt_id=attempt_id,
                ai_call_id=ai_call_id,
                solution_text=solution_text,
                points=points,
                max_points=max_points,
                criteria_json=json.dumps([c.__dict__ for c in criteria], ensure_ascii=False),
                summary=summary,
                status=status,
                created_at=at,
            )
            s.add(row)
            s.flush()
            return self._part2_grade(row)

    def list_part2_grades(self, task_id: int | None = None, limit: int = 50) -> list[Part2Grade]:
        query = select(Part2GradeRow).order_by(
            Part2GradeRow.created_at.desc(), Part2GradeRow.id.desc()
        )
        if task_id is not None:
            query = query.where(Part2GradeRow.task_id == task_id)
        with self._session() as s:
            return [self._part2_grade(row) for row in s.scalars(query.limit(limit))]

    def get_part2_grade(self, grade_id: int) -> Part2Grade | None:
        with self._session() as s:
            row = s.get(Part2GradeRow, grade_id)
            return self._part2_grade(row) if row else None
