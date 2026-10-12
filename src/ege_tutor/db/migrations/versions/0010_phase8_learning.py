"""phase 8: learning cycle (ADR-0022)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

OLD_KINDS = "kind IN ('DIAGNOSTIC', 'REVIEW', 'MISTAKE', 'PRACTICE', 'CONTROL')"
NEW_KINDS = (
    "kind IN ('DIAGNOSTIC', 'REVIEW', 'MISTAKE', 'PRACTICE', 'CONTROL', 'LESSON', 'HOMEWORK')"
)
STEPS = (
    "'THEORY'",
    "'EXAMPLES'",
    "'INDEPENDENT'",
    "'CHECK'",
    "'MISTAKE_REVIEW'",
    "'MISTAKE_TASKS'",
    "'HOMEWORK'",
    "'DONE'",
)


def _replace_kind_check(check: str) -> None:
    with op.batch_alter_table("plan_item", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_plan_item_planitemkind"), type_="check")
        batch_op.create_check_constraint(op.f("ck_plan_item_planitemkind"), check)


def upgrade() -> None:
    _replace_kind_check(NEW_KINDS)

    op.create_table(
        "lesson",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("skill_code", sa.String(length=100), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mistake_skills_json", sa.Text(), nullable=False),
        sa.Column("homework_due", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(f"step IN ({', '.join(STEPS)})", name=op.f("ck_lesson_lessonstep")),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DONE', 'ABANDONED')", name=op.f("ck_lesson_lessonstatus")
        ),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_lesson_subject")
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_lesson_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson")),
    )
    with op.batch_alter_table("lesson", schema=None) as batch_op:
        batch_op.create_index("ix_lesson_skill", ["skill_code"], unique=False)

    op.create_table(
        "lesson_attempt",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "role IN ('INDEPENDENT', 'MISTAKE', 'HOMEWORK')",
            name=op.f("ck_lesson_attempt_lessontaskrole"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_lesson_attempt_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lesson.id"], name=op.f("fk_lesson_attempt_lesson_id_lesson")
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_lesson_attempt")),
    )
    with op.batch_alter_table("lesson_attempt", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_lesson_attempt_lesson_id"), ["lesson_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("lesson_attempt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lesson_attempt_lesson_id"))
    op.drop_table("lesson_attempt")
    with op.batch_alter_table("lesson", schema=None) as batch_op:
        batch_op.drop_index("ix_lesson_skill")
    op.drop_table("lesson")
    op.execute("DELETE FROM plan_item WHERE kind IN ('LESSON', 'HOMEWORK')")
    _replace_kind_check(OLD_KINDS)
