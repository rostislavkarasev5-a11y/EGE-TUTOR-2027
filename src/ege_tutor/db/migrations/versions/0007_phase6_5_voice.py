"""phase 6.5: voice tutor (ADR-0018)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 12:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OLD_PURPOSES = "purpose IN ('HINT', 'EXPLAIN', 'MISTAKE', 'PART2', 'GENERATE')"
NEW_PURPOSES = (
    "purpose IN ('HINT', 'EXPLAIN', 'MISTAKE', 'PART2', 'GENERATE', 'CHAT', 'SPEECH', 'LISTEN')"
)


def _replace_purpose_check(table: str, check: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(f"ck_{table}_aipurpose"), type_="check")
        batch_op.create_check_constraint(op.f(f"ck_{table}_aipurpose"), check)


def upgrade() -> None:
    for table in ("ai_call", "ai_note"):
        _replace_purpose_check(table, NEW_PURPOSES)

    op.create_table(
        "ai_chat_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("speech", sa.Text(), nullable=True),
        sa.Column("ai_call_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('STUDENT', 'TUTOR')", name=op.f("ck_ai_chat_message_chatrole")
        ),
        sa.ForeignKeyConstraint(
            ["ai_call_id"], ["ai_call.id"], name=op.f("fk_ai_chat_message_ai_call_id_ai_call")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_ai_chat_message_attempt_id_attempt")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_chat_message")),
    )
    with op.batch_alter_table("ai_chat_message", schema=None) as batch_op:
        batch_op.create_index("ix_ai_chat_message_attempt", ["attempt_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ai_chat_message", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_chat_message_attempt")
    op.drop_table("ai_chat_message")
    for table in ("ai_note", "ai_call"):
        _replace_purpose_check(table, OLD_PURPOSES)
