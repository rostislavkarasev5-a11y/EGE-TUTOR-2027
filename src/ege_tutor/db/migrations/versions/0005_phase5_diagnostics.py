"""phase 5: adaptive diagnostics

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 17:12:20.253057
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STOP_REASON_CHECK = (
    "stop_reason IN ('PRECISE', 'TASK_BUDGET', 'TIME_BUDGET', 'NO_GAIN', 'NO_TASKS', 'USER')"
)


def upgrade() -> None:
    op.create_table(
        "diagnostic_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("forecast_mean", sa.Float(), nullable=True),
        sa.Column("forecast_low", sa.Float(), nullable=True),
        sa.Column("forecast_high", sa.Float(), nullable=True),
        sa.Column("forecast_max_points", sa.Integer(), nullable=True),
        sa.Column("forecast_interval", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'FINISHED', 'ABANDONED')",
            name=op.f("ck_diagnostic_session_diagnosticstatus"),
        ),
        sa.CheckConstraint(STOP_REASON_CHECK, name=op.f("ck_diagnostic_session_stopreason")),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')",
            name=op.f("ck_diagnostic_session_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_diagnostic_session_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_session")),
    )
    with op.batch_alter_table("diagnostic_session", schema=None) as batch_op:
        batch_op.create_index(
            "ix_diagnostic_session_subject", ["subject", "started_at"], unique=False
        )

    op.create_table(
        "diagnostic_result",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("exam_item", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("basis", sa.String(length=32), nullable=False),
        sa.Column("answered", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "basis IN ('DIRECT', 'INFERRED', 'NOT_ASSESSED')",
            name=op.f("ck_diagnostic_result_itembasis"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_diagnostic_result_confidence_range")
        ),
        sa.CheckConstraint(
            "probability BETWEEN 0 AND 1", name=op.f("ck_diagnostic_result_probability_range")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["diagnostic_session.id"],
            name=op.f("fk_diagnostic_result_session_id_diagnostic_session"),
        ),
        sa.PrimaryKeyConstraint("session_id", "exam_item", name=op.f("pk_diagnostic_result")),
    )
    op.create_table(
        "diagnostic_attempt",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_diagnostic_attempt_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["diagnostic_session.id"],
            name=op.f("fk_diagnostic_attempt_session_id_diagnostic_session"),
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_diagnostic_attempt")),
    )
    with op.batch_alter_table("diagnostic_attempt", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_diagnostic_attempt_session_id"), ["session_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("diagnostic_attempt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_diagnostic_attempt_session_id"))

    op.drop_table("diagnostic_attempt")
    op.drop_table("diagnostic_result")
    with op.batch_alter_table("diagnostic_session", schema=None) as batch_op:
        batch_op.drop_index("ix_diagnostic_session_subject")

    op.drop_table("diagnostic_session")
