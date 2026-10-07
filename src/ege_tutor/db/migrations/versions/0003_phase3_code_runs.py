"""phase 3: test cases and code runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07 12:41:42.548086
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_test_case",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("files_json", sa.Text(), server_default="{}", nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_task_test_case_position_positive")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_test_case_task_id_task")
        ),
        sa.PrimaryKeyConstraint("task_id", "position", name=op.f("pk_task_test_case")),
    )
    op.create_table(
        "code_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("tests_total", sa.Integer(), nullable=False),
        sa.Column("tests_passed", sa.Integer(), nullable=False),
        sa.Column("failed_test", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('OK', 'WRONG_ANSWER', 'TIME_LIMIT', 'MEMORY_LIMIT', "
            "'RUNTIME_ERROR', 'SYNTAX_ERROR')",
            name=op.f("ck_code_run_codeverdict"),
        ),
        sa.CheckConstraint(
            "tests_passed BETWEEN 0 AND tests_total",
            name=op.f("ck_code_run_tests_passed_range"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_code_run_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_code_run_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_run")),
    )
    with op.batch_alter_table("code_run", schema=None) as batch_op:
        batch_op.create_index("ix_code_run_task_created", ["task_id", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("code_run", schema=None) as batch_op:
        batch_op.drop_index("ix_code_run_task_created")

    op.drop_table("code_run")
    op.drop_table("task_test_case")
