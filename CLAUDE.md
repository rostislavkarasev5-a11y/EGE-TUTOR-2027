# CLAUDE.md — правила проекта EGE-TUTOR-2027

Этот файл читает каждая сессия Claude, работающая с репозиторием. Правила обязательны.

## Владелец и общение

- Владелец проекта — новичок в программировании. Объясняй простым русским языком.
- Перед каждым действием, которое должен сделать владелец, давай короткую пошаговую инструкцию.
- Всю работу с Git (ветки, коммиты, PR, CI) выполняет Claude. От владельца — только «Merge» и запуск `.bat`-файлов.

## Утверждённая архитектура (v2.1, 2026-10-07)

```
CLI / WEB
    ↓
TutorApp (фасад, src/ege_tutor/core/app.py)
    ↓
CORE: profile · catalog · attempts · hints · mastery · mistakes · review · calendar ·
      planner · discipline · diagnostics · tests · mocks · exam mode · timer ·
      analytics · forecast
    ↓
MATH / INFORMATICS tutors (src/ege_tutor/subjects/)
    ↓
порты (src/ege_tutor/core/ports/): Repository · AIService · Sandbox · Clock
```

- Вся логика — в CORE. CLI и Web только вызывают `TutorApp` и показывают результат.
- CORE обращается к внешнему миру только через порты.
- **ИИ предлагает → CORE принимает решение → CORE записывает результат.**
- Система максимально независима от ИИ: большинство функций работает без Claude API.
- Подробно: `docs/architecture/ARCHITECTURE.md`, решения: `docs/decisions/`.

## Стек

Python 3.13+, uv, SQLite, SQLAlchemy 2, Alembic, PyYAML (ADR-0010), Pydantic v2, Typer, Rich, pytest, Hypothesis, Ruff, GitHub Actions, SymPy (вспомогательно). anthropic SDK — только с Phase 6. FastAPI/Web — Phase 12, выполняется сразу после Phase 2 (ADR-0013). Зависимость добавляется в фазе, где используется (ADR-0003).

## Главные принципы

1. Все данные пользователя принадлежат приложению, а не ИИ.
2. ИИ — заменяемый сервис.
3. Сырые попытки пользователя никогда не удаляются из истории.
4. Система объяснима и тестируема.
5. Exam Mode полностью исключает `AIService` (правила — ADR-0009).
6. `AI_GENERATED` задания всегда явно помечены и никогда не выдаются за задания ФИПИ.
7. Официальные материалы ФИПИ имеют высший приоритет.
8. Даты экзаменов не хардкодятся: `status = "TBD"` до официального расписания (ADR-0005).
9. У каждой задачи: `source`, `source_ref`, `source_version` (nullable), `verification_status` (ADR-0007).
10. Mastery v0 — экспериментальная модель: `e ∈ [0,1]`, сложность только в весе `w = difficulty_weight × mode_weight`, коэффициенты в `config/mastery.toml` (ADR-0006).
11. Sandbox на Windows: Docker Desktop, запасной WSL2, реализация в Phase 3 (ADR-0008).

## Roadmap

Фазы 0–12 — `docs/roadmap/ROADMAP.md`. Текущая фаза указана в `CURRENT_PHASE` (`src/ege_tutor/core/app.py`) и в README.

## Запреты

- **Не реализовывать будущие фазы раньше времени.** Делай только текущую фазу; заделы «на будущее» — только интерфейсы, которые нужны текущей фазе.
- **Не менять архитектуру, стек, структуру данных или правила обучения без ADR и явного подтверждения владельца.** Если изменение нужно: остановись → опиши проблему → предложи ADR со статусом `Proposed` → дождись подтверждения.
- Не притворяться, что функция работает, если она не реализована. Нереализованное честно сообщает о себе (например, `UnavailableSandbox`).

## Публичный GitHub

Репозиторий публичный (ADR-0004).

- Никогда не коммить: `.env`, ключи API и токены, базы данных (`*.db`, `*.sqlite*`), `data/`, `private_content/`, `private_assets/`, `config/local.toml`.
- Никогда не коммить реальные персональные данные пользователя (включая расписание) и задачи из сборников/ФИПИ. Примеры задач в `content/sample/` пишет только Claude и помечает их `AI_GENERATED`.
- Перед каждым коммитом: `uv run python scripts/check_secrets.py`. В тестах фальшивые секреты собирай во время выполнения.
- Не используй реальные ключи; Claude API ключ не нужен до Phase 6.

## Правила разработки

- Каждая фаза — отдельная ветка и отдельный PR, с тестами. Следующая фаза — только после подтверждения владельца.
- Перед PR должны проходить:
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run pytest
  uv run python scripts/check_secrets.py
  ```
- CI (GitHub Actions) запускает их на Ubuntu и Windows. PR доводится до зелёного CI.
- Тесты не отключаются и не пропускаются ради зелёного CI.
- Стиль: Ruff (длина строки 100), комментарии и docstring — на русском.
