# EGE-TUTOR-2027

Персональная система подготовки к ЕГЭ 2027 по **профильной математике** и **информатике**. Цель — 90+ баллов по каждому предмету.

Приложение само хранит данные, историю, расписание, попытки, ошибки и mastery. Claude используется как заменяемый интеллектуальный слой: **ИИ предлагает → CORE принимает решение → CORE записывает результат.**

## Статус

**Phase 4 — освоение навыков, ошибки и повторения.** После каждой попытки программа пересчитывает, насколько освоен каждый навык (Mastery v0 — стартовая экспериментальная модель, [ADR-0006](docs/decisions/0006-mastery-v0-experimental.md), [ADR-0015](docs/decisions/0015-mastery-v0-details.md)), учитывает забывание и записывает ошибки с причиной. Причину сначала угадывает простое правило, её можно уточнить. Темы, которые пора освежить, и частые ошибки попадают в очередь повторений: на сайте это кнопка «Повторить» и страницы «Прогресс» и «Ошибки». Уже есть: программы на Python в песочнице (Phase 3), решение задач с подсказками (Phase 2), сайт на своём сервере (Phase 12), база и импорт задач (Phase 1). Дальше — [roadmap](docs/roadmap/ROADMAP.md).

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
ege mastery [-s math] [--by item|topic|skill] [--calibration]  освоение
ege mistakes                   последние и частые ошибки
ege mistake НОМЕР КАТЕГОРИЯ    уточнить причину ошибки
ege queue [-s math]            очередь повторений
ege repeat [-s math]           повторять по очереди
ege recalc                     пересчитать освоение по всей истории
ege run ID ФАЙЛ.py             запустить свою программу к задаче по информатике
ege runs [--task ID]           история запусков программ
ege backup [--dir ПАПКА] [--keep 14]  резервная копия базы
```

Шаблоны файлов с задачами — в [content/templates](content/templates/README.md). Примеры задач
(созданы ИИ, помечены `AI_GENERATED`) — `content/sample/tasks.yaml`.

### Песочница для программ на компьютере (Windows)

На сайте песочница уже настроена. Чтобы `ege run` работал на компьютере, нужен
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (ADR-0008):

1. Установи Docker Desktop и запусти его (значок кита внизу экрана).
2. В папке программы открой консоль (`ege-console.bat`) и один раз собери образ:
   `docker build -t ege-tutor:latest .`
3. Проверь: `ege info` — в строке «Python Sandbox» должно быть «да».

## Сайт на своём сервере

Сайт — тот же `TutorApp`, только в браузере: решение задач, проверка ответов, история,
импорт файлов, профиль и скачивание копии базы. Ставится на VPS с Ubuntu 24.04 одной
командой, работает по https, сам обновляется из ветки `main` и каждую ночь делает копию базы.
Подробно — [docs/deploy/SERVER.md](docs/deploy/SERVER.md).

Посмотреть сайт на своём компьютере:

```bash
uv run ege-web set-password
uv run ege-web serve --insecure-cookies   # открыть http://127.0.0.1:8000
```

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

Те же проверки автоматически запускает GitHub Actions на Linux и Windows для каждого PR. Отдельно CI проверяет скрипты сервера (shellcheck), собирает Docker-образ и запускает в нём сайт.

## Данные и приватность

Репозиторий публичный. Личная база (`data/`), задачи из сборников и ФИПИ (`data/private_content/`) и ключи (`.env`) хранятся только на компьютере пользователя или на его собственном сервере (`/var/lib/ege-tutor`, ADR-0013) и в Git не попадают. Подробнее — [ADR-0004](docs/decisions/0004-public-repository-and-private-data.md).

Задания с меткой `AI_GENERATED` созданы ИИ и не являются заданиями ФИПИ.
