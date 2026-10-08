"""phase 7: planner, calendar, discipline (ADR-0019)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 19:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "SCHOOL",
                "TRAINING",
                "COMPETITION",
                "TRIP",
                "REST",
                "ILLNESS",
                "OTHER",
                name="eventkind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("blocks_study", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('SCHOOL', 'TRAINING', 'COMPETITION', 'TRIP', 'REST', 'ILLNESS', 'OTHER')",
            name=op.f("ck_calendar_event_eventkind"),
        ),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_calendar_event_event_order")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_event")),
    )
    with op.batch_alter_table("calendar_event", schema=None) as batch_op:
        batch_op.create_index("ix_calendar_event_starts_at", ["starts_at"], unique=False)

    op.create_table(
        "calendar_window",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute",
            name=op.f("ck_calendar_window_minute_range"),
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_calendar_window_weekday_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_window")),
    )
    op.create_table(
        "daily_checkin",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("fatigue", sa.Integer(), nullable=False),
        sa.Column("available_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "available_minutes IS NULL OR available_minutes BETWEEN 0 AND 1440",
            name=op.f("ck_daily_checkin_available_range"),
        ),
        sa.CheckConstraint("fatigue BETWEEN 1 AND 5", name=op.f("ck_daily_checkin_fatigue_range")),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_daily_checkin")),
    )
    op.create_table(
        "daily_plan",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.Column("budget_minutes", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_daily_plan")),
    )
    op.create_table(
        "discipline_day",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("due_minutes", sa.Integer(), nullable=False),
        sa.Column("done_minutes", sa.Float(), nullable=False),
        sa.Column("due_items", sa.Integer(), nullable=False),
        sa.Column("done_items", sa.Integer(), nullable=False),
        sa.Column("excused", sa.Boolean(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_discipline_day")),
    )
    op.create_table(
        "control_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "subject",
            sa.Enum(
                "MATH_PROFILE",
                "INFORMATICS",
                name="subject",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("exam_item", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "PASSED",
                "FAILED",
                name="controlstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("task_ids_json", sa.Text(), nullable=False),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("passed_tasks", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'PASSED', 'FAILED')",
            name=op.f("ck_control_session_controlstatus"),
        ),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_control_session_subject")
        ),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_control_session_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_control_session")),
    )
    with op.batch_alter_table("control_session", schema=None) as batch_op:
        batch_op.create_index("ix_control_session_item", ["subject", "exam_item"], unique=False)

    op.create_table(
        "plan_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "DIAGNOSTIC",
                "REVIEW",
                "MISTAKE",
                "PRACTICE",
                "CONTROL",
                name="planitemkind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "subject",
            sa.Enum(
                "MATH_PROFILE",
                "INFORMATICS",
                name="subject",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("exam_item", sa.Integer(), nullable=True),
        sa.Column("skill_code", sa.String(length=100), nullable=True),
        sa.Column("tasks", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("added_by_user", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PLANNED",
                "DONE",
                "PARTIAL",
                "MISSED",
                "MOVED",
                "EXCUSED",
                "REMOVED",
                name="planitemstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("carried_from", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('DIAGNOSTIC', 'REVIEW', 'MISTAKE', 'PRACTICE', 'CONTROL')",
            name=op.f("ck_plan_item_planitemkind"),
        ),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'DONE', 'PARTIAL', 'MISSED', 'MOVED', 'EXCUSED', 'REMOVED')",
            name=op.f("ck_plan_item_planitemstatus"),
        ),
        sa.CheckConstraint(
            "subject IN ('MATH_PROFILE', 'INFORMATICS')", name=op.f("ck_plan_item_subject")
        ),
        sa.CheckConstraint("minutes >= 1", name=op.f("ck_plan_item_minutes_positive")),
        sa.CheckConstraint("tasks >= 1", name=op.f("ck_plan_item_tasks_positive")),
        sa.ForeignKeyConstraint(
            ["subject"], ["subject.code"], name=op.f("fk_plan_item_subject_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_item")),
    )
    with op.batch_alter_table("plan_item", schema=None) as batch_op:
        batch_op.create_index("ix_plan_item_day", ["day"], unique=False)

    op.create_table(
        "control_attempt",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["attempt.id"], name=op.f("fk_control_attempt_attempt_id_attempt")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["control_session.id"],
            name=op.f("fk_control_attempt_session_id_control_session"),
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_control_attempt")),
    )
    with op.batch_alter_table("control_attempt", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_control_attempt_session_id"), ["session_id"], unique=False
        )

    with op.batch_alter_table("student", schema=None) as batch_op:
        batch_op.add_column(sa.Column("utc_offset_hours", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("student", schema=None) as batch_op:
        batch_op.drop_column("utc_offset_hours")

    with op.batch_alter_table("control_attempt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_control_attempt_session_id"))

    op.drop_table("control_attempt")
    with op.batch_alter_table("plan_item", schema=None) as batch_op:
        batch_op.drop_index("ix_plan_item_day")

    op.drop_table("plan_item")
    with op.batch_alter_table("control_session", schema=None) as batch_op:
        batch_op.drop_index("ix_control_session_item")

    op.drop_table("control_session")
    op.drop_table("discipline_day")
    op.drop_table("daily_plan")
    op.drop_table("daily_checkin")
    op.drop_table("calendar_window")
    with op.batch_alter_table("calendar_event", schema=None) as batch_op:
        batch_op.drop_index("ix_calendar_event_starts_at")

    op.drop_table("calendar_event")
