# EGE-TUTOR-2027

Персональная система подготовки к ЕГЭ 2027 по **профильной математике** и **информатике**. Цель — 90+ баллов по каждому предмету.

Приложение само хранит данные, историю, расписание, попытки, ошибки и mastery. Claude используется как заменяемый интеллектуальный слой: **ИИ предлагает → CORE принимает решение → CORE записывает результат.**

## Статус

**Phase 0 — Foundation.** Готов фундамент: структура проекта, конфигурация, порты, фасад `TutorApp`, CLI, тесты, CI и защита от публикации секретов. Учебных функций пока нет — они появляются по фазам, см. [roadmap](docs/roadmap/ROADMAP.md).

## Документация

- [Архитектура](docs/architecture/ARCHITECTURE.md)
- [Roadmap](docs/roadmap/ROADMAP.md)
- [Архитектурные решения (ADR)](docs/decisions/README.md)
- [Правила для Claude](CLAUDE.md)

## Запуск (для разработки)

Нужен [uv](https://docs.astral.sh/uv/). Он сам установит Python 3.13 и зависимости.

```bash
uv sync                 # установить зависимости
uv run ege --version    # версия
uv run ege info         # состояние: фаза, даты экзаменов, компоненты
```

Простая установка для Windows двойным щелчком (`install.bat`, `update.bat`) появится в Phase 1.

## Проверки

```bash
uv run ruff check .                     # стиль и ошибки
uv run ruff format --check .            # форматирование
uv run pytest                           # тесты
uv run python scripts/check_secrets.py  # нет ли секретов в репозитории
```

Те же проверки автоматически запускает GitHub Actions на Linux и Windows для каждого PR.

## Данные и приватность

Репозиторий публичный. Личная база (`data/`), задачи из сборников и ФИПИ (`data/private_content/`) и ключи (`.env`) хранятся только на компьютере пользователя и закрыты `.gitignore`. Подробнее — [ADR-0004](docs/decisions/0004-public-repository-and-private-data.md).

Задания с меткой `AI_GENERATED` созданы ИИ и не являются заданиями ФИПИ.
