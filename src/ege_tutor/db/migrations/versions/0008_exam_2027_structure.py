"""exam 2027 structure: renumber tasks (ADR-0020)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12 09:00:00.000000

Миграция только данных: схема не меняется. Номера заданий у задач и результатов диагностики
переводятся на структуру ЕГЭ 2027. Попытки не трогаются — они ссылаются на задачу, а не на номер.
"""

import hashlib
import re

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# старый номер → новый номер (ADR-0020)
MATH = {6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 11: 12, 13: 14, 14: 15, 15: 16, 16: 13, 17: 18, 18: 19}
MATH[19] = 20
INFORMATICS = {13: 10, 23: 13}
# номера, которых в ЕГЭ 2027 нет: их задачи скрываются (как при откате импорта), история остаётся
RETIRED = {"MATH_PROFILE": 12, "INFORMATICS": 10}
# в 2027 номер стал заданием с кратким ответом
NOW_SHORT = {"MATH_PROFILE": {13}}

STARTER_PREFIX = "EGE-TUTOR-2027, стартовый банк: "
STARTER_WORD = {"MATH_PROFILE": "математика", "INFORMATICS": "информатика"}
NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


def _hash(subject: str, exam_item: int, statement: str) -> str:
    """Копия content_hash из content_import: миграция не зависит от кода приложения."""
    normalized = " ".join(statement.lower().split())
    return hashlib.sha256(f"{subject}|{exam_item}|{normalized}".encode()).hexdigest()


def _source_ref(ref: str | None, subject: str, old: int, new: int) -> str | None:
    if ref is None or not ref.startswith(STARTER_PREFIX):
        return ref
    word = STARTER_WORD[subject]
    return ref.replace(f"{word} №{old}, задача", f"{word} №{new}, задача")


def _renumber(mapping: dict[str, dict[int, int]], retired: dict[str, int] | None) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, subject, exam_item, statement, source_ref, answer, answer_type, is_active "
            "FROM task"
        )
    ).all()
    # Сначала скрываем задачи снятых номеров, потом переносим остальные:
    # иначе перенесённая задача может совпасть по хэшу со скрываемой.
    for row in rows:
        if retired and retired.get(row.subject) == row.exam_item and row.is_active:
            conn.execute(sa.text("UPDATE task SET is_active = 0 WHERE id = :id"), {"id": row.id})
    for row in rows:
        new = mapping.get(row.subject, {}).get(row.exam_item)
        if new is None:
            continue
        values = {
            "id": row.id,
            "exam_item": new,
            "hash": _hash(row.subject, new, row.statement),
            "ref": _source_ref(row.source_ref, row.subject, row.exam_item, new),
            "answer_type": row.answer_type,
            "is_active": row.is_active,
        }
        if new in NOW_SHORT.get(row.subject, set()) and row.answer_type == "EXTENDED":
            if row.answer is not None and NUMBER.match(row.answer.strip()):
                values["answer_type"] = "NUMBER"
            else:
                values["is_active"] = (
                    0  # без числового ответа задачу с кратким ответом не проверить
                )
        conn.execute(
            sa.text(
                "UPDATE task SET exam_item = :exam_item, content_hash = :hash, source_ref = :ref, "
                "answer_type = :answer_type, is_active = :is_active WHERE id = :id"
            ),
            values,
        )

    # Результаты диагностики — оценки по номерам (не сырые попытки). Оценки снятых номеров
    # удаляются: такого номера больше нет, а сами попытки диагностики остаются.
    results = conn.execute(
        sa.text(
            "SELECT r.session_id, r.exam_item, s.subject FROM diagnostic_result r "
            "JOIN diagnostic_session s ON s.id = r.session_id"
        )
    ).all()
    for r in results:
        if retired and retired.get(r.subject) == r.exam_item:
            conn.execute(
                sa.text("DELETE FROM diagnostic_result WHERE session_id = :s AND exam_item = :n"),
                {"s": r.session_id, "n": r.exam_item},
            )
    # через временные номера, чтобы не нарушить первичный ключ (сессия, номер)
    for r in results:
        new = mapping.get(r.subject, {}).get(r.exam_item)
        if new is not None:
            conn.execute(
                sa.text(
                    "UPDATE diagnostic_result SET exam_item = :tmp "
                    "WHERE session_id = :s AND exam_item = :n"
                ),
                {"tmp": 1000 + new, "s": r.session_id, "n": r.exam_item},
            )
    conn.execute(
        sa.text("UPDATE diagnostic_result SET exam_item = exam_item - 1000 WHERE exam_item > 1000")
    )


def upgrade() -> None:
    _renumber({"MATH_PROFILE": MATH, "INFORMATICS": INFORMATICS}, RETIRED)


def downgrade() -> None:
    # Обратный перенос номеров. Скрытые задачи снятых номеров остаются скрытыми,
    # удалённые оценки диагностики не восстанавливаются, тип ответа не возвращается.
    back = {
        "MATH_PROFILE": {new: old for old, new in MATH.items()},
        "INFORMATICS": {new: old for old, new in INFORMATICS.items()},
    }
    _renumber(back, None)
