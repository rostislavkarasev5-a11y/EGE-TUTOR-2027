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
    assert spec.item(6).time_norm_seconds == 4 * 60
    engine.dispose()
