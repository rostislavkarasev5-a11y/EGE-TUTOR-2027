# EGE-TUTOR-2027

Персональная система подготовки к ЕГЭ 2027 по **профильной математике** и **информатике**. Цель — 90+ баллов по каждому предмету.

Приложение само хранит данные, историю, расписание, попытки, ошибки и mastery. Claude используется как заменяемый интеллектуальный слой: **ИИ предлагает → CORE принимает решение → CORE записывает результат.**

## Статус

**Phase 2 — решение задач.** Можно решать задачи с таймером и подсказками: программа проверяет ответ как на бланке ЕГЭ, сравнивает время с нормативом и записывает каждую попытку. Перед решением эталонный ответ задачи проверяется командой `ege review`. Уже есть с Phase 1: локальная база, профиль, структура экзаменов, каталог тем, импорт задач, установка двойным щелчком. Дальше — [roadmap](docs/roadmap/ROADMAP.md).

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
ege review [ID]                проверить эталонные ответы задач
ege solve [ID] [-s math] [-n 6]  решать: ? — подсказка, сдаюсь, похожая, выход
ege attempts [--task ID]       история попыток
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
