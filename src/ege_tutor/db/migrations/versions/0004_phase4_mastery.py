"""phase 4 mastery

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07 16:51:27.611573
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

CATEGORY_CHECK = (
    "category IN ('TOPIC_GAP', 'FORMULA', 'CONDITION', 'ALGORITHM', 'CARELESS', 'ARITHMETIC', "
    "'PROGRAMMING', 'SYNTAX', 'TIME', 'FORMATTING', 'STRATEGY')"
)


def upgrade() -> None:
    op.create_table(
        "mastery",
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("value_raw", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("stability_days", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_practiced_at", sa.DateTime(), nullable=False),
        sa.Column("next_review_on", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_mastery_confidence_range")),
        sa.CheckConstraint("value_raw BETWEEN 0 AND 1", name=op.f("ck_mastery_value_raw_range")),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_mastery_skill_code_skill")
        ),
        sa.PrimaryKeyConstraint("skill_code", name=op.f("pk_mastery")),
    )
    op.create_table(
        "mastery_snapshot",
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("value_raw", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint("value BETWEEN 0 AND 1", name=op.f("ck_mastery_snapshot_value_range")),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_mastery_snapshot_skill_code_skill")
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_date", "skill_code", "model_version", name=op.f("pk_mastery_snapshot")
        ),
    )
    op.create_table(
        "mistake",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("skill_code", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("classified_by", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("replaces_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            CATEGORY_CHECK,
            name=op.f("ck_mistake_mistakecategory"),
        ),
        sa.CheckConstraint(
            "classified_by IN ('RULE', 'AI', 'USER')", name=op.f("ck_mistake_classifiedby")
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_mistake_confidence_range")),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_mistake_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["replaces_id"], ["mistake.id"], name=op.f("fk_mistake_replaces_id_mistake")
        ),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_mistake_skill_code_skill")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_mistake_task_id_task")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mistake")),
    )
    with op.batch_alter_table("mistake", schema=None) as batch_op:
        batch_op.create_index("ix_mistake_skill", ["skill_code"], unique=False)

    op.create_table(
        "mistake_pattern",
        sa.Column("skill_code", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("first_at", sa.DateTime(), nullable=False),
        sa.Column("last_at", sa.DateTime(), nullable=False),
        sa.Column("independent_streak", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.CheckConstraint(
            CATEGORY_CHECK,
            name=op.f("ck_mistake_pattern_mistakecategory"),
        ),
        sa.ForeignKeyConstraint(
            ["skill_code"], ["skill.code"], name=op.f("fk_mistake_pattern_skill_code_skill")
        ),
        sa.PrimaryKeyConstraint("skill_code", "category", name=op.f("pk_mistake_pattern")),
    )
    op.create_table(
        "prediction_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("predicted", sa.Float(), nullable=False),
        sa.Column("outcome", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN (0, 1)", name=op.f("ck_prediction_log_outcome_binary")
        ),
        sa.CheckConstraint(
            "predicted BETWEEN 0 AND 1", name=op.f("ck_prediction_log_predicted_range")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_prediction_log_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_prediction_log_task_id_task")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prediction_log")),
        sa.UniqueConstraint("attempt_id", name=op.f("uq_prediction_log_attempt_id")),
    )


def downgrade() -> None:
    op.drop_table("prediction_log")
    op.drop_table("mistake_pattern")
    with op.batch_alter_table("mistake", schema=None) as batch_op:
        batch_op.drop_index("ix_mistake_skill")

    op.drop_table("mistake")
    op.drop_table("mastery_snapshot")
    op.drop_table("mastery")
