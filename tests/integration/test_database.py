"""Хранилище SQLite: миграции, каталог, профиль, ограничения схемы."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from ege_tutor.config import load_settings
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import Subject
from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.db.engine import make_engine, upgrade_to_head
from ege_tutor.db.models import Base
from ege_tutor.db.repository import SqlRepository


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    upgrade_to_head(engine)
    yield engine
    engine.dispose()


def test_migrations_match_models(engine):
    """Схема после миграций совпадает с моделями: миграцию не забыли."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_upgrade_is_idempotent(engine):
    upgrade_to_head(engine)
    assert inspect(engine).has_table("task")


def test_foreign_keys_are_enforced(engine):
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO topic (code, subject, title, position) VALUES ('X', 'NOPE', 't', 0)")
        )


def test_task_without_source_ref_is_rejected_by_schema(engine):
    repo = SqlRepository(engine)
    repo.sync_catalog(load_catalog(load_settings().content_dir))
    with engine.begin() as conn, pytest.raises(IntegrityError, match="source_ref"):
        conn.execute(
            text(
                "INSERT INTO task (subject, exam_item, statement, answer_type, source, source_ref,"
                " verification_status, content_hash, is_active, created_at) VALUES"
                " ('MATH_PROFILE', 1, 'x', 'NUMBER', 'USER_MATERIAL', '  ', 'UNVERIFIED', 'h', 1,"
                " :now)"
            ),
            {"now": "2026-01-01 00:00:00"},
        )


def test_sync_catalog_is_idempotent(tutor):
    before = tutor.topics(Subject.MATH_PROFILE)
    tutor.repository.sync_catalog(tutor.catalog)
    tutor.repository.sync_catalog(tutor.catalog)
    assert tutor.topics(Subject.MATH_PROFILE) == before
    assert len(tutor.exam_spec(Subject.INFORMATICS).items) == 27


def test_topics_round_trip_through_db(tutor):
    from_db = {t.code: t for t in tutor.topics(Subject.INFORMATICS)}
    for topic in tutor.catalog.topics_of(Subject.INFORMATICS):
        stored = from_db[topic.code]
        assert [s.code for s in stored.skills] == [s.code for s in topic.skills]
        for a, b in zip(stored.skills, topic.skills, strict=True):
            assert set(a.exam_items) == set(b.exam_items)
            assert set(a.requires) == set(b.requires)


def test_data_survives_reopen(tutor, data_dir):
    tutor.update_profile(display_name="Ученик", targets={Subject.INFORMATICS: 95})
    tutor.close()
    reopened = TutorApp.create()
    try:
        profile = reopened.profile()
        assert profile.display_name == "Ученик"
        assert profile.targets[Subject.INFORMATICS] == 95
        assert profile.targets[Subject.MATH_PROFILE] == 90
    finally:
        reopened.close()
    assert (data_dir / "ege.db").is_file()


def test_profile_defaults_and_validation(tutor):
    profile = tutor.profile()
    assert profile.display_name is None
    assert profile.targets == {Subject.MATH_PROFILE: 90, Subject.INFORMATICS: 90}
    with pytest.raises(AppError):
        tutor.update_profile(targets={Subject.MATH_PROFILE: 101})
    with pytest.raises(AppError):
        tutor.update_profile(display_name="x" * 101)
    assert tutor.update_profile(display_name="  ").display_name is None


def test_phase1_database_upgrades_and_keeps_data(tmp_path, fixed_clock):
    """update.bat на компьютере пользователя: база Phase 1 обновляется, данные остаются."""
    from alembic import command

    from ege_tutor.db.engine import alembic_config

    engine = make_engine(tmp_path / "old.db")
    command.upgrade(alembic_config(engine), "0001")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO subject (code) VALUES ('MATH_PROFILE'), ('INFORMATICS')"))
        conn.execute(text("INSERT INTO student (id, display_name) VALUES (1, 'Ученик')"))
    upgrade_to_head(engine)
    repo = SqlRepository(engine)
    repo.sync_catalog(load_catalog(load_settings().content_dir))
    assert repo.get_profile().display_name == "Ученик"
    spec = repo.get_exam_spec(Subject.MATH_PROFILE)
    assert spec.item(7).time_norm_seconds == 4 * 60
    engine.dispose()


def test_exam_2027_migration_renumbers_tasks(tmp_path):
    """Миграция 0008 (ADR-0020): номера задач переходят на ЕГЭ 2027, попытки не трогаются."""
    from alembic import command

    from ege_tutor.core.services.content_import import content_hash
    from ege_tutor.db.engine import alembic_config

    engine = make_engine(tmp_path / "old.db")
    command.upgrade(alembic_config(engine), "0007")
    starter = "EGE-TUTOR-2027, стартовый банк: {} №{}, задача 1"
    tasks = [  # id, предмет, старый номер, условие, тип ответа, ответ, source_ref
        (1, "MATH_PROFILE", 6, "Уравнение", "NUMBER", "6", starter.format("математика", 6)),
        (2, "MATH_PROFILE", 12, "Минимум функции", "NUMBER", "2", "мой конспект"),
        (3, "MATH_PROFILE", 16, "Кредит", "EXTENDED", "1332000", "мой конспект"),
        (4, "MATH_PROFILE", 16, "Вклад без ответа", "EXTENDED", None, "мой конспект"),
        (5, "MATH_PROFILE", 19, "Числа", "EXTENDED", "7", "мой конспект"),
        (6, "INFORMATICS", 10, "Поиск слов", "NUMBER", "5", "мой конспект"),
        (7, "INFORMATICS", 13, "Маска", "NUMBER", "3", starter.format("информатика", 13)),
        (8, "INFORMATICS", 23, "Программы", "NUMBER", "9", "мой конспект"),
        (9, "INFORMATICS", 1, "Граф", "NUMBER", "4", "мой конспект"),
    ]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO subject (code) VALUES ('MATH_PROFILE'), ('INFORMATICS')"))
        for task_id, subject, item, statement, kind, answer, ref in tasks:
            conn.execute(
                text(
                    "INSERT INTO task (id, subject, exam_item, statement, answer_type, answer, "
                    "source, source_ref, verification_status, content_hash, is_active, "
                    "created_at) VALUES (:id, :subject, :item, :statement, :kind, :answer, "
                    "'USER_MATERIAL', :ref, 'REVIEWED', :hash, 1, '2026-10-01 10:00:00')"
                ),
                {
                    "id": task_id,
                    "subject": subject,
                    "item": item,
                    "statement": statement,
                    "kind": kind,
                    "answer": answer,
                    "ref": ref,
                    "hash": content_hash(Subject(subject), item, statement),
                },
            )
        conn.execute(
            text(
                "INSERT INTO diagnostic_session (id, subject, status, started_at, model_version) "
                "VALUES (1, 'MATH_PROFILE', 'FINISHED', '2026-10-01 10:00:00', 'diag-v0')"
            )
        )
        for item in (6, 7, 12, 16):
            conn.execute(
                text(
                    "INSERT INTO diagnostic_result (session_id, exam_item, probability, "
                    "confidence, basis, answered) VALUES (1, :n, 0.5, 0.5, 'DIRECT', 1)"
                ),
                {"n": item},
            )
    upgrade_to_head(engine)
    with engine.connect() as conn:
        rows = {
            r.id: r
            for r in conn.execute(
                text(
                    "SELECT id, subject, exam_item, statement, answer_type, is_active, "
                    "source_ref, content_hash FROM task"
                )
            )
        }
        results = sorted(
            conn.execute(text("SELECT exam_item FROM diagnostic_result")).scalars().all()
        )
    expected = {1: 7, 2: 12, 3: 13, 4: 13, 5: 20, 6: 10, 7: 10, 8: 13, 9: 1}
    assert {i: r.exam_item for i, r in rows.items()} == expected
    assert {i for i, r in rows.items() if not r.is_active} == {2, 4, 6}  # снятые и без ответа
    assert rows[3].answer_type == "NUMBER"  # №13 в 2027 — краткий ответ
    assert rows[5].answer_type == "EXTENDED"
    assert rows[1].source_ref == starter.format("математика", 7)
    assert rows[7].source_ref == starter.format("информатика", 10)
    for r in rows.values():  # повторная загрузка той же задачи распознается как дубль
        assert r.content_hash == content_hash(Subject(r.subject), r.exam_item, r.statement)
    assert results == [7, 8, 13]  # оценка снятого №12 удалена, остальные перенесены
    engine.dispose()
