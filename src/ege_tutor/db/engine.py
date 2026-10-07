"""Подключение к SQLite и применение миграций."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", MIGRATIONS_DIR.as_posix())
    config.attributes["engine"] = engine
    return config


def upgrade_to_head(engine: Engine) -> None:
    """Довести схему базы до последней версии. Данные пользователя сохраняются."""
    command.upgrade(alembic_config(engine), "head")


def is_migrated(engine: Engine) -> bool:
    return inspect(engine).has_table("alembic_version")
