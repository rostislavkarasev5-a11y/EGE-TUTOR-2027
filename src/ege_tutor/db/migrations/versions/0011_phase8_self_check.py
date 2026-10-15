"""phase 8: self-check of part 2 (ADR-0022, п. 5)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15 10:00:00.000000

Попытка получает балл части 2 (points, max_points), оценка части 2 — статус SELF.
Столбцы попытки добавляются обычным ALTER TABLE ADD COLUMN, без пересоздания таблицы attempt:
на неё ссылаются многие таблицы, а пересоздание при включённых внешних ключах опасно.
Диапазон балла проверяет CORE.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

OLD_STATUSES = "status IN ('AI_PRELIMINARY')"
NEW_STATUSES = "status IN ('AI_PRELIMINARY', 'SELF')"


def _replace_status_check(check: str) -> None:
    with op.batch_alter_table("part2_grade", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_part2_grade_part2gradestatus"), type_="check")
        batch_op.create_check_constraint(op.f("ck_part2_grade_part2gradestatus"), check)


def upgrade() -> None:
    op.add_column("attempt", sa.Column("points", sa.Integer(), nullable=True))
    op.add_column("attempt", sa.Column("max_points", sa.Integer(), nullable=True))
    _replace_status_check(NEW_STATUSES)


def downgrade() -> None:
    # Самооценки без статуса SELF хранить негде; сами попытки остаются (принцип 3).
    op.execute("DELETE FROM part2_grade WHERE status = 'SELF'")
    _replace_status_check(OLD_STATUSES)
    op.drop_column("attempt", "max_points")
    op.drop_column("attempt", "points")
