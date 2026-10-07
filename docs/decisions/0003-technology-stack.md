# ADR-0003: Стек технологий и порядок подключения зависимостей

- Статус: Accepted
- Дата: 2026-10-07

## Решение

| Слой | Технология |
|---|---|
| Язык | Python 3.13+ |
| Пакеты, окружение | uv (`uv.lock` в Git) |
| БД | SQLite + SQLAlchemy 2 + Alembic |
| Модели и конфигурация | Pydantic v2, TOML |
| CLI | Typer + Rich |
| Математика | SymPy — только вспомогательная проверка выражений и ответов |
| Тесты, стиль | pytest, Hypothesis, Ruff (lint + format) |
| CI | GitHub Actions (Ubuntu + Windows) |
| ИИ | anthropic SDK — только с Phase 6 |
| Web | FastAPI — только в будущих фазах |

Зависимость добавляется в `pyproject.toml` в той фазе, где она реально используется: Phase 0 — Pydantic, Typer, Rich (+ dev: pytest, Hypothesis, Ruff); Phase 1 — SQLAlchemy, Alembic; Phase 2 — SymPy; Phase 6 — anthropic; Phase 12 — FastAPI.

## Последствия

В Phase 0 нет неиспользуемых зависимостей. Замена любой технологии из таблицы — только новым ADR и с подтверждения владельца.
