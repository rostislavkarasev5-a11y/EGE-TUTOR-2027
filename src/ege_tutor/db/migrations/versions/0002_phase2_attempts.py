"""phase 2: attempts, hints, time norms

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 08:24:28.249473
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_normalized", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("max_hint_level", sa.Integer(), nullable=False),
        sa.Column("time_norm_seconds", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "mode IN ('PRACTICE', 'HOMEWORK', 'REVIEW', 'CONTROL', 'DIAGNOSTIC', 'MOCK', 'EXAM')",
            name=op.f("ck_attempt_attemptmode"),
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'ANSWERED', 'GAVE_UP', 'ABANDONED')",
            name=op.f("ck_attempt_attemptstatus"),
        ),
        sa.CheckConstraint(
            "verdict IN ('CORRECT', 'WRONG', 'WRONG_FORMAT')", name=op.f("ck_attempt_verdict")
        ),
        sa.CheckConstraint("attempt_no >= 1", name=op.f("ck_attempt_attempt_no_positive")),
        sa.CheckConstraint(
            "max_hint_level BETWEEN 0 AND 4", name=op.f("ck_attempt_max_hint_level_range")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_attempt_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempt")),
    )
    with op.batch_alter_table("attempt", schema=None) as batch_op:
        batch_op.create_index("ix_attempt_task_started", ["task_id", "started_at"], unique=False)

    op.create_table(
        "task_hint",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name=op.f("ck_task_hint_level_range")),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_task_hint_task_id_task")),
        sa.PrimaryKeyConstraint("task_id", "level", name=op.f("pk_task_hint")),
    )
    op.create_table(
        "hint_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("shown_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("level BETWEEN 1 AND 4", name=op.f("ck_hint_event_level_range")),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_hint_event_attempt_id_attempt")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hint_event")),
    )
    with op.batch_alter_table("exam_spec", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("time_norm_source", sa.Text(), server_default="", nullable=False)
        )

    with op.batch_alter_table("exam_spec_item", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("time_norm_seconds", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("exam_spec_item", schema=None) as batch_op:
        batch_op.drop_column("time_norm_seconds")

    with op.batch_alter_table("exam_spec", schema=None) as batch_op:
        batch_op.drop_column("time_norm_source")

    op.drop_table("hint_event")
    op.drop_table("task_hint")
    with op.batch_alter_table("attempt", schema=None) as batch_op:
        batch_op.drop_index("ix_attempt_task_started")

    op.drop_table("attempt")
