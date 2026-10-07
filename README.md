# EGE-TUTOR-2027

Персональная система подготовки к ЕГЭ 2027 по **профильной математике** и **информатике**. Цель — 90+ баллов по каждому предмету.

Приложение само хранит данные, историю, расписание, попытки, ошибки и mastery. Claude используется как заменяемый интеллектуальный слой: **ИИ предлагает → CORE принимает решение → CORE записывает результат.**

## Статус

**Phase 1 — данные, каталог и импорт контента.** Есть локальная база SQLite, профиль с целями, структура обоих экзаменов (предварительная, по демоверсии 2026), каталог тем и навыков, импорт задач из YAML/CSV с проверкой, отчётом и отменой, установка двойным щелчком. Решать задачи в программе можно будет с Phase 2, см. [roadmap](docs/roadmap/ROADMAP.md).

## Документация

- [Архитектура](docs/architecture/ARCHITECTURE.md)
- [Roadmap](docs/roadmap/ROADMAP.md)
- [Архитектурные решения (ADR)](docs/decisions/README.md)
- [Правила для Claude](CLAUDE.md)

## Установка на Windows

1. Установи [Git](https://git-scm.com/download/win) и [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Скачай `install.bat` из репозитория и запусти двойным щелчком. Он скачает проект в
   `%USERPROFILE%\EGE-TUTOR-2027`, установит Python и библиотеки, создаст базу и ярлык
   `EGE-TUTOR.bat` на рабочем столе.
3. Обновление — `update.bat` в папке проекта. Личные данные при обновлении не трогаются.

## Команды

```text
ege info                       состояние программы
ege profile [--name ...] [--target-math 90] [--target-informatics 90]
ege exam math|informatics      структура экзамена
ege topics [-s math] [--skills]
ege import ФАЙЛ [--apply]      проверить файл с задачами / добавить задачи
ege imports                    история импортов
ege undo-import НОМЕР          отменить импорт
ege tasks [-s math] [-n 6] [--source AI_GENERATED]
ege task ID [--answer]
```

Шаблоны файлов с задачами — в [content/templates](content/templates/README.md). Примеры задач
(созданы ИИ, помечены `AI_GENERATED`) — `content/sample/tasks.yaml`.

## Запуск (для разработки)

Нужен [uv](https://docs.astral.sh/uv/). Он сам установит Python 3.13 и зависимости.

```bash
uv sync                 # установить зависимости
uv run ege --version    # версия
uv run ege info         # состояние: фаза, даты экзаменов, компоненты
```

Папку данных можно переопределить переменной `EGE_TUTOR_DATA_DIR` (так делают тесты).

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
