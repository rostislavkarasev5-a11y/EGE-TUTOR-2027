"""phase 1: catalog, profile, tasks, imports

Revision ID: 0001
Revises:
Create Date: 2026-10-07 07:47:11.178580
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("added_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ROLLED_BACK')", name=op.f("ck_import_batch_importbatchstatus")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batch")),
    )
    op.create_table(
        "student",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_student_single_student")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student")),
    )
    op.create_table(
        "subject",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "code IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_subject_subject")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_subject")),
    )
    op.create_table(
        "exam_spec",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("exam_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_exam_spec_subject")
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_exam_spec_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_spec")),
        sa.UniqueConstraint("subject", "exam_year", name=op.f("uq_exam_spec_subject")),
    )
    op.create_table(
        "student_target",
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("target_score", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_student_target_subject")
        ),
        sa.CheckConstraint(
            "target_score BETWEEN 0 AND 100", name=op.f("ck_student_target_target_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_student_target_subject_subject")
        ),
        sa.PrimaryKeyConstraint("subject", name=op.f("pk_student_target")),
    )
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("exam_item", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("answer_type", sa.String(length=32), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("time_norm_seconds", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "answer_type IN ('NUMBER', 'TEXT', 'SEQUENCE', 'EXTENDED')",
            name=op.f("ck_task_answertype"),
        ),
        sa.CheckConstraint(
            "source IN ('OFFICIAL_FIPI', 'OPEN_BANK', 'USER_MATERIAL', 'AI_GENERATED')",
            name=op.f("ck_task_tasksource"),
        ),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_task_subject")
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('UNVERIFIED', 'AUTO_CHECKED', 'REVIEWED', 'DISPUTED', 'REJECTED')",
            name=op.f("ck_task_verificationstatus"),
        ),
        sa.CheckConstraint(
            "difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name=op.f("ck_task_difficulty")
        ),
        sa.CheckConstraint(
            "length(trim(source_ref)) > 0", name=op.f("ck_task_source_ref_not_empty")
        ),
        sa.CheckConstraint("length(trim(statement)) > 0", name=op.f("ck_task_statement_not_empty")),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batch.id"],
            name=op.f("fk_task_import_batch_id_import_batch"),
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_task_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
    )
    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.create_index(
            "uq_task_active_content_hash",
            ["content_hash"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )

    op.create_table(
        "topic",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("parent_code", sa.String(length=32), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_topic_subject")
        ),
        sa.ForeignKeyConstraint(
            ["parent_code"], ["topic.code"], name=op.f("fk_topic_parent_code_topic")
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_topic_subject_subject")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_topic")),
    )
    op.create_table(
        "exam_spec_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spec_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("answer_kind", sa.String(length=32), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "answer_kind IN ('short', 'extended')", name=op.f("ck_exam_spec_item_answerkind")
        ),
        sa.CheckConstraint("max_points > 0", name=op.f("ck_exam_spec_item_max_points_positive")),
        sa.ForeignKeyConstraint(
            ["spec_id"], ["exam_spec.id"], name=op.f("fk_exam_spec_item_spec_id_exam_spec")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_spec_item")),
        sa.UniqueConstraint("spec_id", "number", name=op.f("uq_exam_spec_item_spec_id")),
    )
    op.create_table(
        "skill",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("topic_code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["topic_code"], ["topic.code"], name=op.f("fk_skill_topic_code_topic")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_skill")),
    )
    op.create_table(
        "task_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_task_asset_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_asset")),
    )
    op.create_table(
        "skill_exam_item",
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.Column("exam_item", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_skill_exam_item_skill_code_skill")
        ),
        sa.PrimaryKeyConstraint("skill_code", "exam_item", name=op.f("pk_skill_exam_item")),
    )
    op.create_table(
        "skill_prerequisite",
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.Column("requires_code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["requires_code"],
            ["skill.code"],
            name=op.f("fk_skill_prerequisite_requires_code_skill"),
        ),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_skill_prerequisite_skill_code_skill")
        ),
        sa.PrimaryKeyConstraint("skill_code", "requires_code", name=op.f("pk_skill_prerequisite")),
    )
    op.create_table(
        "task_skill",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_task_skill_skill_code_skill")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_task_skill_task_id_task")),
        sa.PrimaryKeyConstraint("task_id", "skill_code", name=op.f("pk_task_skill")),
    )


def downgrade() -> None:
    op.drop_table("task_skill")
    op.drop_table("skill_prerequisite")
    op.drop_table("skill_exam_item")
    op.drop_table("task_asset")
    op.drop_table("skill")
    op.drop_table("exam_spec_item")
    op.drop_table("topic")
    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.drop_index("uq_task_active_content_hash", sqlite_where=sa.text("is_active = 1"))

    op.drop_table("task")
    op.drop_table("student_target")
    op.drop_table("exam_spec")
    op.drop_table("subject")
    op.drop_table("student")
    op.drop_table("import_batch")
