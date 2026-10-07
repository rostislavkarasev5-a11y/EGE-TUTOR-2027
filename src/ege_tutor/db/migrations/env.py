"""Окружение Alembic. Подключение передаётся из ege_tutor.db.engine."""

from alembic import context

from ege_tutor.db.models import Base

engine = context.config.attributes["engine"]

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite не умеет ALTER большинства ограничений
    )
    with context.begin_transaction():
        context.run_migrations()
