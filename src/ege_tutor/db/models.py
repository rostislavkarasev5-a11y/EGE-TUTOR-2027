"""ORM-модели SQLAlchemy 2. Схема меняется только через миграции Alembic."""

import datetime as dt
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ege_tutor.core.domain import (
    AnswerKind,
    AnswerType,
    AttemptMode,
    AttemptStatus,
    CodeVerdict,
    ImportBatchStatus,
    Subject,
    TaskSource,
    Verdict,
    VerificationStatus,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator):
    """Время в UTC. SQLite не хранит часовой пояс, поэтому приводим явно."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("ожидается время с часовым поясом")
        return value.astimezone(dt.UTC).replace(tzinfo=None)

    def process_result_value(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        return None if value is None else value.replace(tzinfo=dt.UTC)


def _enum(enum_cls: type[StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        name=enum_cls.__name__.lower(),
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ── каталог ─────────────────────────────────────────────────────────────────


class SubjectRow(Base):
    __tablename__ = "subject"

    code: Mapped[Subject] = mapped_column(_enum(Subject), primary_key=True)


class ExamSpecRow(Base):
    __tablename__ = "exam_spec"
    __table_args__ = (UniqueConstraint("subject", "exam_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[Subject] = mapped_column(_enum(Subject), ForeignKey("subject.code"))
    exam_year: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int]
    time_norm_source: Mapped[str] = mapped_column(Text, server_default="")

    items: Mapped[list["ExamSpecItemRow"]] = relationship(
        back_populates="spec", cascade="all, delete-orphan", order_by="ExamSpecItemRow.number"
    )


class ExamSpecItemRow(Base):
    __tablename__ = "exam_spec_item"
    __table_args__ = (
        UniqueConstraint("spec_id", "number"),
        CheckConstraint("max_points > 0", name="max_points_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    spec_id: Mapped[int] = mapped_column(ForeignKey("exam_spec.id"))
    number: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    part: Mapped[int]
    answer_kind: Mapped[AnswerKind] = mapped_column(_enum(AnswerKind))
    max_points: Mapped[int]
    time_norm_seconds: Mapped[int] = mapped_column(server_default="0")

    spec: Mapped[ExamSpecRow] = relationship(back_populates="items")


class TopicRow(Base):
    __tablename__ = "topic"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[Subject] = mapped_column(_enum(Subject), ForeignKey("subject.code"))
    title: Mapped[str] = mapped_column(Text)
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("topic.code"))
    position: Mapped[int] = mapped_column(default=0)

    skills: Mapped[list["SkillRow"]] = relationship(
        back_populates="topic", order_by="SkillRow.position"
    )


class SkillRow(Base):
    __tablename__ = "skill"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_code: Mapped[str] = mapped_column(ForeignKey("topic.code"))
    title: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(default=0)

    topic: Mapped[TopicRow] = relationship(back_populates="skills")


class SkillExamItemRow(Base):
    """Какие номера заданий ЕГЭ проверяют навык."""

    __tablename__ = "skill_exam_item"

    skill_code: Mapped[str] = mapped_column(ForeignKey("skill.code"), primary_key=True)
    exam_item: Mapped[int] = mapped_column(primary_key=True)


class SkillPrerequisiteRow(Base):
    __tablename__ = "skill_prerequisite"

    skill_code: Mapped[str] = mapped_column(ForeignKey("skill.code"), primary_key=True)
    requires_code: Mapped[str] = mapped_column(ForeignKey("skill.code"), primary_key=True)


# ── профиль ─────────────────────────────────────────────────────────────────


class StudentRow(Base):
    __tablename__ = "student"
    __table_args__ = (CheckConstraint("id = 1", name="single_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(100))


class StudentTargetRow(Base):
    __tablename__ = "student_target"
    __table_args__ = (CheckConstraint("target_score BETWEEN 0 AND 100", name="target_score_range"),)

    subject: Mapped[Subject] = mapped_column(
        _enum(Subject), ForeignKey("subject.code"), primary_key=True
    )
    target_score: Mapped[int]


# ── задачи и импорт ─────────────────────────────────────────────────────────


class ImportBatchRow(Base):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    file_name: Mapped[str] = mapped_column(Text)
    file_format: Mapped[str] = mapped_column(String(16))
    added_count: Mapped[int]
    rejected_count: Mapped[int]
    status: Mapped[ImportBatchStatus] = mapped_column(_enum(ImportBatchStatus))
    rolled_back_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    report_json: Mapped[str] = mapped_column(Text)


class TaskRow(Base):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint("length(trim(statement)) > 0", name="statement_not_empty"),
        CheckConstraint("length(trim(source_ref)) > 0", name="source_ref_not_empty"),
        CheckConstraint("difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="difficulty"),
        # Одинаковая действующая задача может быть только одна; выведенные из оборота не мешают.
        Index(
            "uq_task_active_content_hash",
            "content_hash",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[Subject] = mapped_column(_enum(Subject), ForeignKey("subject.code"))
    exam_item: Mapped[int]
    statement: Mapped[str] = mapped_column(Text)
    answer_type: Mapped[AnswerType] = mapped_column(_enum(AnswerType))
    answer: Mapped[str | None] = mapped_column(Text)
    solution: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    time_norm_seconds: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[TaskSource] = mapped_column(_enum(TaskSource))
    source_ref: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[VerificationStatus] = mapped_column(_enum(VerificationStatus))
    verified_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    content_hash: Mapped[str] = mapped_column(String(64))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)

    skills: Mapped[list["TaskSkillRow"]] = relationship(cascade="all, delete-orphan")
    assets: Mapped[list["TaskAssetRow"]] = relationship(cascade="all, delete-orphan")
    hints: Mapped[list["TaskHintRow"]] = relationship(
        cascade="all, delete-orphan", order_by="TaskHintRow.level"
    )
    tests: Mapped[list["TaskTestCaseRow"]] = relationship(
        cascade="all, delete-orphan", order_by="TaskTestCaseRow.position"
    )


class TaskSkillRow(Base):
    __tablename__ = "task_skill"

    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True)
    skill_code: Mapped[str] = mapped_column(ForeignKey("skill.code"), primary_key=True)


class TaskAssetRow(Base):
    """Файл к задаче (txt, xlsx…). Сам файл лежит в data/private_content/assets/."""

    __tablename__ = "task_asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"))
    file_name: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]


class TaskHintRow(Base):
    """Записанная подсказка к задаче. Уровни 1–3; уровень 4 — это solution задачи."""

    __tablename__ = "task_hint"
    __table_args__ = (CheckConstraint("level BETWEEN 1 AND 3", name="level_range"),)

    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True)
    level: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)


class TaskTestCaseRow(Base):
    """Тест-кейс для программы к задаче информатики (Phase 3)."""

    __tablename__ = "task_test_case"
    __table_args__ = (CheckConstraint("position >= 1", name="position_positive"),)

    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str] = mapped_column(Text)
    files_json: Mapped[str] = mapped_column(Text, server_default="{}")


# ── попытки ─────────────────────────────────────────────────────────────────


class AttemptRow(Base):
    """Попытка решения. Строки никогда не удаляются (принцип 3)."""

    __tablename__ = "attempt"
    __table_args__ = (
        CheckConstraint("max_hint_level BETWEEN 0 AND 4", name="max_hint_level_range"),
        CheckConstraint("attempt_no >= 1", name="attempt_no_positive"),
        Index("ix_attempt_task_started", "task_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"))
    mode: Mapped[AttemptMode] = mapped_column(_enum(AttemptMode))
    attempt_no: Mapped[int]
    status: Mapped[AttemptStatus] = mapped_column(_enum(AttemptStatus))
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    answer: Mapped[str | None] = mapped_column(Text)  # как ввёл пользователь, без изменений
    answer_normalized: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[Verdict | None] = mapped_column(_enum(Verdict))
    max_hint_level: Mapped[int] = mapped_column(default=0)
    time_norm_seconds: Mapped[int | None] = mapped_column(Integer)

    task: Mapped[TaskRow] = relationship()


class HintEventRow(Base):
    """Факт показа подсказки в попытке."""

    __tablename__ = "hint_event"
    __table_args__ = (CheckConstraint("level BETWEEN 1 AND 4", name="level_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempt.id"))
    level: Mapped[int]
    shown_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class CodeRunRow(Base):
    """Запуск программы к задаче (Phase 3). Строки никогда не удаляются."""

    __tablename__ = "code_run"
    __table_args__ = (
        CheckConstraint("tests_passed BETWEEN 0 AND tests_total", name="tests_passed_range"),
        Index("ix_code_run_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"))
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempt.id"))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    code: Mapped[str] = mapped_column(Text)
    verdict: Mapped[CodeVerdict] = mapped_column(_enum(CodeVerdict))
    tests_total: Mapped[int]
    tests_passed: Mapped[int]
    failed_test: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str] = mapped_column(Text)
    stderr: Mapped[str] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float] = mapped_column(Float)
