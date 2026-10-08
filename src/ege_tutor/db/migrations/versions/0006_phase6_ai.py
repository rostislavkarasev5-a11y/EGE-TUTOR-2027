"""phase 6: ai layer

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 11:03:07.554381
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PURPOSE_CHECK = "purpose IN ('HINT', 'EXPLAIN', 'MISTAKE', 'PART2', 'GENERATE')"
CATEGORY_CHECK = (
    "category IN ('TOPIC_GAP', 'FORMULA', 'CONDITION', 'ALGORITHM', 'CARELESS', 'ARITHMETIC', "
    "'PROGRAMMING', 'SYNTAX', 'TIME', 'FORMATTING', 'STRATEGY')"
)


def upgrade() -> None:
    op.create_table(
        "ai_call",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_rub", sa.Float(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(PURPOSE_CHECK, name=op.f("ck_ai_call_aipurpose")),
        sa.CheckConstraint(
            "status IN ('OK', 'REJECTED', 'ERROR')", name=op.f("ck_ai_call_aicallstatus")
        ),
        sa.CheckConstraint("cost_rub >= 0", name=op.f("ck_ai_call_cost_non_negative")),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_ai_call_tokens_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_ai_call_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_ai_call_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_call")),
    )
    with op.batch_alter_table("ai_call", schema=None) as batch_op:
        batch_op.create_index("ix_ai_call_created_at", ["created_at"], unique=False)

    op.create_table(
        "ai_note",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ai_call_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("mistake_id", sa.Integer(), nullable=True),
        sa.Column("hint_level", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(CATEGORY_CHECK, name=op.f("ck_ai_note_mistakecategory")),
        sa.CheckConstraint(PURPOSE_CHECK, name=op.f("ck_ai_note_aipurpose")),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name=op.f("ck_ai_note_confidence")
        ),
        sa.CheckConstraint(
            "hint_level IS NULL OR hint_level BETWEEN 1 AND 3", name=op.f("ck_ai_note_hint_level")
        ),
        sa.ForeignKeyConstraint(
            ["ai_call_id"], ["ai_call.id"], name=op.f("fk_ai_note_ai_call_id_ai_call")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_ai_note_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["mistake_id"], ["mistake.id"], name=op.f("fk_ai_note_mistake_id_mistake")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_ai_note_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_note")),
    )
    with op.batch_alter_table("ai_note", schema=None) as batch_op:
        batch_op.create_index("ix_ai_note_attempt", ["attempt_id"], unique=False)
        batch_op.create_index("ix_ai_note_mistake", ["mistake_id"], unique=False)

    op.create_table(
        "part2_grade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("ai_call_id", sa.Integer(), nullable=True),
        sa.Column("solution_text", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.Column("criteria_json", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('AI_PRELIMINARY')", name=op.f("ck_part2_grade_part2gradestatus")
        ),
        sa.CheckConstraint(
            "points BETWEEN 0 AND max_points", name=op.f("ck_part2_grade_points_range")
        ),
        sa.ForeignKeyConstraint(
            ["ai_call_id"], ["ai_call.id"], name=op.f("fk_part2_grade_ai_call_id_ai_call")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_part2_grade_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_part2_grade_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_part2_grade")),
    )
    with op.batch_alter_table("part2_grade", schema=None) as batch_op:
        batch_op.create_index("ix_part2_grade_task", ["task_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("part2_grade", schema=None) as batch_op:
        batch_op.drop_index("ix_part2_grade_task")
    op.drop_table("part2_grade")
    with op.batch_alter_table("ai_note", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_note_mistake")
        batch_op.drop_index("ix_ai_note_attempt")
    op.drop_table("ai_note")
    with op.batch_alter_table("ai_call", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_call_created_at")
    op.drop_table("ai_call")
