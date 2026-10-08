"""CLI на Typer. Только ввод/вывод: вся логика — в TutorApp."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ege_tutor import __version__
from ege_tutor.config import ConfigError
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    ITEM_BASIS_NAMES,
    MISTAKE_CATEGORY_NAMES,
    SOURCE_LABELS,
    STOP_REASON_NAMES,
    AnswerKind,
    AnswerType,
    Attempt,
    AttemptMode,
    AttemptStatus,
    CodeRun,
    CodeVerdict,
    DiagnosticSession,
    DiagnosticState,
    DiagnosticStatus,
    Forecast,
    ImportBatchStatus,
    ImportReport,
    ItemBasis,
    MistakeCategory,
    ReviewReason,
    Subject,
    Task,
    TaskSource,
    Verdict,
    VerificationStatus,
)
from ege_tutor.core.services.catalog import CatalogError

SUBJECT_NAMES = {
    Subject.MATH_PROFILE: "Математика (профиль)",
    Subject.INFORMATICS: "Информатика",
}
SUBJECT_SHORT = {Subject.MATH_PROFILE: "М", Subject.INFORMATICS: "И"}
SUBJECT_HELP = "Предмет: math или informatics."
STATUS_NAMES = {
    VerificationStatus.UNVERIFIED: "[yellow]не проверена[/]",
    VerificationStatus.AUTO_CHECKED: "[green]проверена автоматически[/]",
    VerificationStatus.REVIEWED: "[green]проверена[/]",
    VerificationStatus.DISPUTED: "[red]спорная[/]",
    VerificationStatus.REJECTED: "[red]отклонена[/]",
}
VERDICT_NAMES = {
    Verdict.CORRECT: "[green]верно[/]",
    Verdict.WRONG: "[red]неверно[/]",
    Verdict.WRONG_FORMAT: "[yellow]неверный формат[/]",
}
ATTEMPT_STATUS_NAMES = {
    AttemptStatus.IN_PROGRESS: "решается",
    AttemptStatus.ANSWERED: "ответ дан",
    AttemptStatus.GAVE_UP: "сдался",
    AttemptStatus.ABANDONED: "брошена",
}

app = typer.Typer(
    help="EGE-TUTOR-2027 — подготовка к ЕГЭ по профильной математике и информатике.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"EGE-TUTOR-2027 {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-V", help="Показать версию.", callback=_version_callback, is_eager=True
        ),
    ] = False,
) -> None:
    pass


# ── вспомогательное ─────────────────────────────────────────────────────────


def _fail(message: str) -> typer.Exit:
    console.print(f"[red]Ошибка:[/] {message}")
    return typer.Exit(code=1)


def _tutor() -> TutorApp:
    try:
        return TutorApp.create()
    except ConfigError as e:
        raise _fail(f"конфигурация: {e}") from e
    except CatalogError as e:
        raise _fail(f"каталог тем: {e}") from e


def _subject(text: str | None) -> Subject | None:
    if text is None:
        return None
    try:
        return Subject.parse(text)
    except ValueError as e:
        raise _fail(f"неизвестный предмет «{text}». {SUBJECT_HELP}") from e


def _table(**kwargs) -> Table:
    # Только тонкие линии: их умеют рисовать и шрифты старых консолей Windows,
    # а жирные линии там превращаются в «???».
    return Table(box=box.SQUARE, **kwargs)


def _panel(renderable: str | Text, **kwargs) -> Panel:
    return Panel(renderable, box=box.SQUARE, **kwargs)


def _yes_no(value: bool) -> str:
    return "[green]готово[/]" if value else "[yellow]ещё нет[/]"


def _source_text(source: TaskSource) -> str:
    label = SOURCE_LABELS[source]
    return f"[bold magenta]{label}[/]" if source == TaskSource.AI_GENERATED else label


# ── состояние ───────────────────────────────────────────────────────────────


@app.command()
def info() -> None:
    """Состояние программы: фаза, даты экзаменов, доступные компоненты."""
    state = _tutor().info()

    console.print(f"[bold]EGE-TUTOR-2027[/] {state.version} · Phase {state.phase}")

    exams = _table(title="Экзамены")
    exams.add_column("Предмет")
    exams.add_column("Дата")
    exams.add_column("Осталось дней")
    for exam in state.exams:
        if exam.date is None:
            date_text, days_text = "не утверждена (TBD)", "—"
        else:
            date_text = exam.date.isoformat()
            days_text = str(exam.days_left) if exam.days_left is not None else "—"
        exams.add_row(SUBJECT_NAMES[exam.subject], date_text, days_text)
    console.print(exams)

    parts = _table(title="Компоненты")
    parts.add_column("Компонент")
    parts.add_column("Статус")
    parts.add_row("Хранилище (Phase 1)", _yes_no(state.storage_ready))
    parts.add_row("Python Sandbox", _yes_no(state.sandbox_available))
    parts.add_row("AI Layer (Phase 6)", _yes_no(state.ai_available))
    console.print(parts)
    console.print(f"Задач в базе: {state.task_count}")


@app.command()
def init() -> None:
    """Создать или обновить локальную базу данных. Безопасно запускать повторно."""
    tutor = _tutor()
    console.print(f"[green]База готова:[/] {tutor.settings.data_dir}")


@app.command()
def backup(
    folder: Annotated[
        Path | None, typer.Option("--dir", help="Куда сохранить (по умолчанию data/backups).")
    ] = None,
    keep: Annotated[int, typer.Option("--keep", help="Сколько последних копий хранить.")] = 14,
) -> None:
    """Сделать резервную копию базы. Старые копии сверх --keep удаляются."""
    try:
        dest = _tutor().backup(folder, keep)
    except AppError as e:
        raise _fail(str(e)) from e
    console.print(f"[green]Копия базы сохранена:[/] {dest}")


# ── профиль ─────────────────────────────────────────────────────────────────


@app.command()
def profile(
    name: Annotated[str | None, typer.Option("--name", help="Как к тебе обращаться.")] = None,
    target_math: Annotated[
        int | None, typer.Option("--target-math", help="Цель по математике, баллы 0–100.")
    ] = None,
    target_informatics: Annotated[
        int | None,
        typer.Option("--target-informatics", help="Цель по информатике, баллы 0–100."),
    ] = None,
) -> None:
    """Показать профиль или изменить имя и целевые баллы."""
    tutor = _tutor()
    targets = {}
    if target_math is not None:
        targets[Subject.MATH_PROFILE] = target_math
    if target_informatics is not None:
        targets[Subject.INFORMATICS] = target_informatics
    try:
        current = (
            tutor.update_profile(display_name=name, targets=targets)
            if name is not None or targets
            else tutor.profile()
        )
    except AppError as e:
        raise _fail(str(e)) from e

    table = _table(title="Профиль")
    table.add_column("Поле")
    table.add_column("Значение")
    table.add_row("Имя", current.display_name or "—")
    for subject in Subject:
        table.add_row(f"Цель: {SUBJECT_NAMES[subject]}", str(current.targets[subject]))
    console.print(table)


# ── каталог ─────────────────────────────────────────────────────────────────


@app.command()
def exam(subject: Annotated[str, typer.Argument(help=SUBJECT_HELP)]) -> None:
    """Структура экзамена: номера заданий, части и баллы."""
    parsed = Subject.MATH_PROFILE
    try:
        parsed = Subject.parse(subject)
        spec = _tutor().exam_spec(parsed)
    except ValueError as e:
        raise _fail(f"неизвестный предмет «{subject}». {SUBJECT_HELP}") from e
    except AppError as e:
        raise _fail(str(e)) from e
    table = _table(title=f"{SUBJECT_NAMES[parsed]}, ЕГЭ {spec.exam_year} ({spec.status})")
    table.add_column("№", justify="right")
    table.add_column("Задание")
    table.add_column("Часть", justify="center")
    table.add_column("Ответ")
    table.add_column("Баллы", justify="right")
    for item in spec.items:
        kind = "развёрнутый" if item.answer_kind == AnswerKind.EXTENDED else "краткий"
        table.add_row(str(item.number), item.title, str(item.part), kind, str(item.max_points))
    console.print(table)
    console.print(
        f"Максимум первичных баллов: {spec.max_primary_score} · "
        f"время: {spec.duration_minutes} мин\nИсточник: {spec.source}"
    )


@app.command()
def topics(
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
    skills: Annotated[bool, typer.Option("--skills", help="Показать навыки внутри тем.")] = False,
) -> None:
    """Темы и навыки по предметам."""
    tutor = _tutor()
    parsed = _subject(subject)
    for subj in [parsed] if parsed else list(Subject):
        table = _table(title=SUBJECT_NAMES[subj])
        table.add_column("Код")
        table.add_column("Тема / навык")
        table.add_column("Задания ЕГЭ")
        for topic in tutor.topics(subj):
            items = ", ".join(map(str, topic.exam_items)) or "—"
            table.add_row(f"[bold]{topic.code}[/]", f"[bold]{topic.title}[/]", items)
            if skills:
                for skill in topic.skills:
                    table.add_row(
                        f"  {skill.code}", f"  {skill.title}", ", ".join(map(str, skill.exam_items))
                    )
        console.print(table)


# ── импорт ──────────────────────────────────────────────────────────────────


def _print_report(report: ImportReport) -> None:
    console.print(
        f"Файл [bold]{report.file_name}[/] ({report.file_format}): задач в файле {report.total}, "
        f"[green]годных {len(report.accepted)}[/], [red]с ошибками {len(report.rejected_rows)}[/]"
    )
    for title, issues, style in (
        ("Ошибки", report.errors, "red"),
        ("Предупреждения", report.warnings, "yellow"),
    ):
        if not issues:
            continue
        table = _table(title=title, title_style=style)
        table.add_column("Задача", justify="right")
        table.add_column("Что не так")
        for issue in issues:
            table.add_row("файл" if issue.row is None else str(issue.row), issue.message)
        console.print(table)


@app.command(name="import")
def import_(
    file: Annotated[Path, typer.Argument(help="Файл с задачами: .yaml или .csv.")],
    apply: Annotated[
        bool, typer.Option("--apply", help="Записать годные задачи в базу (без него — проверка).")
    ] = False,
) -> None:
    """Проверить файл с задачами и (с --apply) добавить их в базу."""
    tutor = _tutor()
    if not apply:
        report = tutor.preview_import(file)
        _print_report(report)
        if report.accepted and not report.file_error:
            console.print(
                "\nЭто была только проверка. Чтобы добавить годные задачи, запусти:\n"
                f"  [bold]ege import {file} --apply[/]"
            )
        raise typer.Exit(code=1 if report.file_error else 0)

    result = tutor.import_tasks(file)
    _print_report(result.report)
    if result.batch is None:
        raise _fail("ничего не добавлено")
    console.print(
        f"\n[green]Добавлено задач: {result.batch.added_count}[/] (импорт №{result.batch.id}). "
        f"Отменить: [bold]ege undo-import {result.batch.id}[/]"
    )


@app.command()
def imports() -> None:
    """История импортов."""
    batches = _tutor().import_batches()
    if not batches:
        console.print("Импортов пока не было.")
        return
    table = _table(title="Импорты")
    table.add_column("№", justify="right")
    table.add_column("Когда (UTC)")
    table.add_column("Файл")
    table.add_column("Добавлено", justify="right")
    table.add_column("Отклонено", justify="right")
    table.add_column("Статус")
    for b in batches:
        status = (
            "[green]действует[/]" if b.status == ImportBatchStatus.ACTIVE else "[yellow]отменён[/]"
        )
        table.add_row(
            str(b.id),
            b.created_at.strftime("%Y-%m-%d %H:%M"),
            b.file_name,
            str(b.added_count),
            str(b.rejected_count),
            status,
        )
    console.print(table)


@app.command(name="undo-import")
def undo_import(batch_id: Annotated[int, typer.Argument(help="Номер импорта.")]) -> None:
    """Отменить импорт: его задачи перестают выдаваться, история сохраняется."""
    try:
        batch = _tutor().rollback_import(batch_id)
    except AppError as e:
        raise _fail(str(e)) from e
    console.print(f"Импорт №{batch.id} отменён, задач выведено из оборота: {batch.added_count}.")


# ── задачи ──────────────────────────────────────────────────────────────────


@app.command()
def tasks(
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
    item: Annotated[int | None, typer.Option("--item", "-n", help="Номер задания ЕГЭ.")] = None,
    source: Annotated[
        str | None,
        typer.Option("--source", help="OFFICIAL_FIPI, OPEN_BANK, USER_MATERIAL или AI_GENERATED."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Сколько показать.")] = 50,
) -> None:
    """Список задач в базе."""
    parsed_source = None
    if source is not None:
        try:
            parsed_source = TaskSource(source.strip().upper())
        except ValueError as e:
            raise _fail(f"неизвестный источник «{source}»") from e
    found = _tutor().tasks(_subject(subject), item, parsed_source, limit)
    if not found:
        console.print("Задач не найдено.")
        return
    table = _table(title="Задачи")
    table.add_column("ID", justify="right")
    table.add_column("Пр.")
    table.add_column("№", justify="right")
    table.add_column("Условие")
    table.add_column("Источник", no_wrap=True)  # метку ИИ нельзя разрывать (ADR-0007)
    table.add_column("Проверка")
    for t in found:
        statement = " ".join(t.statement.split())
        short = statement if len(statement) <= 45 else statement[:42] + "..."
        table.add_row(
            str(t.id),
            SUBJECT_SHORT[t.subject],
            str(t.exam_item),
            short,
            _source_text(t.source),
            STATUS_NAMES[t.verification_status],
        )
    console.print(table)


@app.command()
def task(
    task_id: Annotated[int, typer.Argument(help="ID задачи из списка ege tasks.")],
    show_answer: Annotated[
        bool, typer.Option("--answer", help="Показать ответ и решение.")
    ] = False,
) -> None:
    """Показать задачу. Источник показывается всегда."""
    tutor = _tutor()
    try:
        t = tutor.task(task_id)
    except AppError as e:
        raise _fail(str(e)) from e
    header = f"Задача {t.id} · {SUBJECT_NAMES[t.subject]} · задание №{t.exam_item}"
    console.print(_panel(t.statement, title=header, title_align="left"))
    console.print(f"Источник: {_source_text(t.source)} — {t.source_ref}")
    if t.source_version:
        console.print(f"Версия источника: {t.source_version}")
    console.print(f"Проверка: {t.verification_status}")
    if t.skills:
        console.print(f"Навыки: {', '.join(t.skills)}")
    for asset in t.assets:
        console.print(f"Файл: {asset.file_name} → {tutor.asset_path(asset)}")
    if t.tests:
        console.print(f"Тестов для программы: {len(t.tests)} (проверка: ege run {t.id} файл.py)")
    if show_answer:
        console.print(f"Ответ: [bold]{_display_answer(t)}[/]")
        if t.solution:
            console.print(_panel(t.solution, title="Решение", title_align="left"))


# ── решение задач (Phase 2) ─────────────────────────────────────────────────

HINT_WORDS = {"?", "подсказка", "hint"}
GIVE_UP_WORDS = {"сдаюсь", "!", "give up"}
SIMILAR_WORDS = {"похожая", "similar"}
EXIT_WORDS = {"выход", "q", "quit", "exit"}
HINT_NAMES = {1: "небольшая подсказка", 2: "конкретная подсказка", 3: "подробное объяснение"}
HINT_NAMES[4] = "полное решение"


def _minutes(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _show_task_for_solving(tutor: TutorApp, t: Task, attempt: Attempt) -> None:
    header = f"Задача {t.id} · {SUBJECT_NAMES[t.subject]} · задание №{t.exam_item}"
    console.print(_panel(t.statement, title=header, title_align="left"))
    console.print(f"Источник: {_source_text(t.source)} — {t.source_ref}")
    for asset in t.assets:
        console.print(f"Файл: {asset.file_name} → {tutor.asset_path(asset)}")
    console.print(
        f"Попытка №{attempt.attempt_no} · норматив {_minutes(attempt.time_norm_seconds)} · "
        "время пошло"
    )
    if attempt.max_hint_level:
        console.print(
            f"[yellow]Подсказки из прошлой попытки учтены (уровень {attempt.max_hint_level}).[/]"
        )
    console.print(
        "[dim]Введи ответ. Команды: ? — подсказка, сдаюсь — показать ответ, "
        "похожая — другая задача того же номера, выход — закончить.[/]"
    )


# «l» и «ytn» — это «д» и «нет», набранные в английской раскладке.
YES_WORDS = {"да", "д", "y", "yes", "l", "lf"}
NO_WORDS = {"нет", "н", "n", "no", "ytn"}


def _ask_yes_no(question: str) -> bool:
    """Вопрос «да/нет»; Enter — да. Понимает русские и английские ответы."""
    while True:
        try:
            reply = typer.prompt(f"{question} [Д/н]", default="да", show_default=False)
        except (typer.Abort, EOFError):
            return False
        reply = reply.strip().casefold()
        if reply in YES_WORDS:
            return True
        if reply in NO_WORDS:
            return False
        console.print("Ответь «да» или «нет».")


def _display_answer(t: Task) -> str:
    if t.answer is None:
        return "—"
    if t.answer_type == AnswerType.NUMBER:
        return t.answer.replace(".", ",")  # как на бланке ЕГЭ
    return t.answer


def _show_answer(t: Task) -> None:
    console.print(f"Правильный ответ: [bold]{_display_answer(t)}[/]")
    if t.solution:
        console.print(_panel(t.solution, title="Решение", title_align="left"))


def _report_result(attempt: Attempt, explanation: str) -> None:
    console.print(f"Итог: {VERDICT_NAMES[attempt.verdict]}")
    if explanation:
        console.print(explanation)
    spent = attempt.time_spent_seconds
    norm_text = ""
    if attempt.within_norm is not None:
        norm_text = " — в нормативе" if attempt.within_norm else " — [yellow]дольше норматива[/]"
    console.print(f"Время: {_minutes(spent)} из {_minutes(attempt.time_norm_seconds)}{norm_text}")
    if attempt.correct:
        if attempt.independent:
            console.print("[green]Решено самостоятельно.[/]")
        else:
            console.print(
                f"Решено с подсказкой уровня {attempt.max_hint_level}: "
                "это не считается самостоятельным решением."
            )


def _solve_one(
    tutor: TutorApp, t: Task, mode: AttemptMode = AttemptMode.PRACTICE
) -> tuple[str, Task | None]:
    """Решать задачу до верного ответа или отказа. Возвращает (что дальше, следующая задача)."""
    while True:
        try:
            attempt = tutor.start_attempt(t.id, mode)
        except AppError as e:
            raise _fail(str(e)) from e
        _show_task_for_solving(tutor, t, attempt)
        while True:
            try:
                text = typer.prompt("Ответ", prompt_suffix=": ").strip()
            except (typer.Abort, EOFError, KeyboardInterrupt):
                tutor.abandon_attempt(attempt.id)
                console.print("\nПопытка прервана, она сохранена как брошенная.")
                return "exit", None
            command = text.casefold()
            if command in HINT_WORDS:
                try:
                    hint = tutor.next_hint(attempt.id)
                except AppError as e:
                    console.print(f"[yellow]{e}[/]")
                    continue
                title = f"Уровень {hint.level}: {HINT_NAMES[hint.level]}"
                console.print(_panel(hint.text, title=title, title_align="left"))
                console.print(f"[dim]Самостоятельность этой попытки теперь {hint.independence}.[/]")
                continue
            if command in EXIT_WORDS:
                tutor.abandon_attempt(attempt.id)
                return "exit", None
            if command in GIVE_UP_WORDS or command in SIMILAR_WORDS:
                tutor.give_up(attempt.id)
                _show_answer(t)
                _report_mistakes(tutor, attempt.id)
                if command in SIMILAR_WORDS:
                    similar = tutor.similar_task(t.id)
                    if similar is None:
                        console.print("Похожих проверенных задач пока нет.")
                        return "next", None
                    return "similar", similar
                return "next", None
            try:
                result = tutor.submit_answer(attempt.id, text)
            except AppError as e:
                console.print(f"[yellow]{e}[/]")
                continue
            _report_result(result.attempt, result.check.explanation)
            _report_mistakes(tutor, attempt.id)
            if result.attempt.correct:
                return "next", None
            if _ask_yes_no("Попробовать ещё раз?"):
                break
            _show_answer(t)
            return "next", None


def _report_mistakes(tutor: TutorApp, attempt_id: int) -> None:
    """Показать, как программа поняла ошибку, и как это уточнить."""
    mistakes = tutor.attempt_mistakes(attempt_id)
    if not mistakes:
        return
    first = mistakes[0]
    console.print(
        f"[dim]Ошибка записана: {first.category_name} — {first.description}. "
        f"Если причина другая: ege mistake {first.id} КАТЕГОРИЯ (список: ege mistake --help).[/]"
    )


@app.command()
def solve(
    task_id: Annotated[int | None, typer.Argument(help="ID задачи (необязательно).")] = None,
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
    item: Annotated[int | None, typer.Option("--item", "-n", help="Номер задания ЕГЭ.")] = None,
) -> None:
    """Решать задачи: таймер, подсказки, проверка ответа. Каждая попытка сохраняется."""
    tutor = _tutor()
    parsed = _subject(subject)
    try:
        current = tutor.task(task_id) if task_id is not None else tutor.next_task(parsed, item)
    except AppError as e:
        raise _fail(str(e)) from e
    while True:
        outcome, following = _solve_one(tutor, current)
        if outcome == "exit":
            return
        if following is None:
            if not _ask_yes_no("Следующая задача?"):
                return
            try:
                following = tutor.next_task(parsed, item)
            except AppError as e:
                console.print(f"[yellow]{e}[/]")
                return
        current = following


STOP_WORDS = {"стоп", "stop", "выход", "q"}
SKIP_WORDS = {"пропустить", "пропуск", "п", "skip", "s"}


def _ask_review_choice() -> str:
    """Спросить «Ответ верный?» и переспрашивать, пока не введут понятный ответ."""
    allowed = YES_WORDS | NO_WORDS | STOP_WORDS | SKIP_WORDS
    while True:
        choice = typer.prompt("Ответ верный", prompt_suffix="? ").strip().casefold()
        if choice in allowed:
            return choice
        console.print("[yellow]Не понял ответ. Напиши: да, нет, пропустить или стоп.[/]")


@app.command()
def review(
    task_id: Annotated[int | None, typer.Argument(help="ID задачи (необязательно).")] = None,
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
    item: Annotated[int | None, typer.Option("--item", "-n", help="Номер задания ЕГЭ.")] = None,
) -> None:
    """Проверить эталонные ответы задач. Проверенные задачи можно решать в ege solve."""
    tutor = _tutor()
    parsed = _subject(subject)
    while True:
        if task_id is not None:
            try:
                t = tutor.task(task_id)
            except AppError as e:
                raise _fail(str(e)) from e
        else:
            t = tutor.next_unverified_task(parsed, item)
            if t is None:
                console.print("Непроверенных задач нет.")
                return
        header = f"Задача {t.id} · {SUBJECT_NAMES[t.subject]} · задание №{t.exam_item}"
        console.print(_panel(t.statement, title=header, title_align="left"))
        console.print(f"Источник: {_source_text(t.source)} — {t.source_ref}")
        _show_answer(t)
        console.print(
            "[dim]Реши сам или сверь с источником. Ответ верный? "
            "да — можно решать; нет — задача станет спорной и не будет выдаваться; "
            "пропустить; стоп.[/]"
        )
        choice = _ask_review_choice()
        if choice in YES_WORDS:
            tutor.review_task(t.id, answer_is_correct=True)
            console.print(f"[green]Задача {t.id} проверена.[/]")
        elif choice in NO_WORDS:
            tutor.review_task(t.id, answer_is_correct=False)
            console.print(f"[yellow]Задача {t.id} помечена как спорная.[/]")
        elif choice in STOP_WORDS:
            return
        if task_id is not None:
            return
        if choice in SKIP_WORDS:
            console.print("Задача пропущена, проверка закончена.")
            return  # эта же задача выпала бы снова


@app.command()
def attempts(
    task_id: Annotated[int | None, typer.Option("--task", "-t", help="Только эта задача.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Сколько показать.")] = 20,
) -> None:
    """История попыток: ответы, время, подсказки. Попытки никогда не удаляются."""
    found = _tutor().attempts(task_id, limit)
    if not found:
        console.print("Попыток пока не было.")
        return
    table = _table(title="Попытки")
    table.add_column("№", justify="right")
    table.add_column("Когда (UTC)")
    table.add_column("Задача", justify="right")
    table.add_column("ЕГЭ", justify="right")
    table.add_column("Ответ")
    table.add_column("Итог")
    table.add_column("Подсказка", justify="right")
    table.add_column("Время / норматив")
    for a in found:
        result = VERDICT_NAMES[a.verdict] if a.verdict else ATTEMPT_STATUS_NAMES[a.status]
        table.add_row(
            str(a.id),
            a.started_at.strftime("%Y-%m-%d %H:%M"),
            f"{a.task_id} (#{a.attempt_no})",
            f"{SUBJECT_SHORT[a.subject]}{a.exam_item}",
            a.answer or "—",
            result,
            str(a.max_hint_level) if a.max_hint_level else "—",
            f"{_minutes(a.time_spent_seconds)} / {_minutes(a.time_norm_seconds)}",
        )
    console.print(table)


# ── mastery, ошибки, повторения (Phase 4) ───────────────────────────────────

REVIEW_REASON_NAMES = {
    ReviewReason.FORGETTING: "пора повторить",
    ReviewReason.MISTAKES: "частая ошибка",
}


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


@app.command()
def mastery(
    subject: Annotated[str, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = "math",
    by: Annotated[
        str, typer.Option("--by", help="Как показать: item (номера ЕГЭ), topic или skill.")
    ] = "item",
    calibration: Annotated[
        bool, typer.Option("--calibration", help="Насколько предсказания совпали с фактом.")
    ] = False,
) -> None:
    """Освоение (Mastery v0, экспериментальная модель): по номерам заданий, темам или навыкам."""
    tutor = _tutor()
    parsed = _subject(subject)
    if parsed is None:
        raise _fail("укажи предмет: --subject math или informatics")
    if by == "skill":
        table = _table(title=f"Навыки · {SUBJECT_NAMES[parsed]}")
        for column in ("Навык", "Освоение", "Уверенность", "Попыток", "Повторить"):
            table.add_column(column)
        found = tutor.skill_masteries(parsed)
        for m in sorted(found, key=lambda m: m.value):
            table.add_row(
                f"{m.skill_code} {tutor.skill_title(m.skill_code)}",
                _percent(m.value),
                _percent(m.confidence),
                str(m.attempts),
                "сейчас" if m.review_due else m.next_review_on.isoformat(),
            )
        if not found:
            console.print("Пока нет решённых задач с навыками.")
            return
    elif by in ("item", "topic"):
        rows = (
            tutor.mastery_by_exam_item(parsed) if by == "item" else tutor.mastery_by_topic(parsed)
        )
        table = _table(title=f"Освоение · {SUBJECT_NAMES[parsed]}")
        table.add_column("№" if by == "item" else "Тема")
        table.add_column("Название")
        table.add_column("Освоение", justify="right")
        table.add_column("Изучено навыков", justify="right")
        for a in rows:
            table.add_row(a.key, a.title, _percent(a.value), f"{a.studied} из {a.total}")
    else:
        raise _fail("--by: item, topic или skill")
    console.print(table)
    console.print(
        "[dim]Mastery v0 — стартовая модель: оценки уточнятся, когда накопится история.[/]"
    )
    if calibration:
        c = tutor.calibration()
        if not c.count:
            console.print("Калибровка: пока нет завершённых предсказаний.")
        else:
            console.print(
                f"Калибровка по {c.count} попыткам: Brier {c.brier}, log-loss {c.log_loss}, "
                f"предсказано в среднем {_percent(c.mean_predicted)}, "
                f"решено самостоятельно {_percent(c.mean_actual)}."
            )


@app.command(name="recalc")
def recalc() -> None:
    """Пересчитать mastery и паттерны ошибок по всей истории попыток."""
    count = _tutor().recalculate_mastery()
    console.print(f"Пересчитано навыков: {count}. Снимки прошлых дней не изменены.")


@app.command()
def mistakes(
    skill: Annotated[str | None, typer.Option("--skill", help="Только этот навык.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Сколько показать.")] = 20,
) -> None:
    """Последние ошибки и частые ошибки (паттерны)."""
    tutor = _tutor()
    patterns = tutor.mistake_patterns()
    if patterns:
        table = _table(title="Частые ошибки")
        for column in ("Навык", "Что не так", "Раз", "Приоритет"):
            table.add_column(column)
        for p in patterns[:limit]:
            table.add_row(
                f"{p.skill_code} {tutor.skill_title(p.skill_code)}",
                p.category_name,
                str(p.occurrences),
                f"{p.priority:.2f}",
            )
        console.print(table)
    found = tutor.mistakes(skill, limit)
    if not found:
        console.print("Ошибок пока нет.")
        return
    table = _table(title="Последние ошибки")
    for column in ("№", "Когда (UTC)", "Задача", "Навык", "Что не так", "Кто решил"):
        table.add_column(column)
    for m in found:
        table.add_row(
            str(m.id),
            m.created_at.strftime("%Y-%m-%d %H:%M"),
            str(m.task_id),
            m.skill_code or "—",
            m.category_name,
            {"RULE": "правило", "AI": "ИИ", "USER": "ты"}[m.classified_by.value],
        )
    console.print(table)


@app.command(name="mistake")
def mistake_fix(
    mistake_id: Annotated[int, typer.Argument(help="Номер ошибки из ege mistakes.")],
    category: Annotated[
        str,
        typer.Argument(
            help="Что пошло не так: "
            + ", ".join(f"{c.value} ({MISTAKE_CATEGORY_NAMES[c]})" for c in MistakeCategory)
        ),
    ],
) -> None:
    """Уточнить причину ошибки. Исходная запись сохраняется в истории."""
    try:
        parsed = MistakeCategory(category.strip().upper())
    except ValueError as e:
        raise _fail(f"неизвестная категория {category}") from e
    try:
        fixed = _tutor().reclassify_mistake(mistake_id, parsed)
    except AppError as e:
        raise _fail(str(e)) from e
    console.print(
        f"Ошибка №{mistake_id}: теперь «{fixed.category_name}» (новая запись №{fixed.id})."
    )


@app.command()
def queue(
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
) -> None:
    """Очередь повторений: что пора повторить и частые ошибки."""
    tutor = _tutor()
    items = tutor.review_queue(_subject(subject))
    if not items:
        console.print("Повторять пока нечего.")
        return
    table = _table(title="Очередь повторений")
    for column in ("Навык", "Почему", "Освоение"):
        table.add_column(column)
    for i in items:
        why = REVIEW_REASON_NAMES[i.reason]
        if i.category is not None:
            why += f": {MISTAKE_CATEGORY_NAMES[i.category]}"
        table.add_row(f"{i.skill_code} {i.skill_title}", why, _percent(i.value))
    console.print(table)
    console.print("Начать повторение: ege repeat")


@app.command()
def repeat(
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
) -> None:
    """Повторять по очереди повторений (режим REVIEW)."""
    tutor = _tutor()
    parsed = _subject(subject)
    while True:
        try:
            task = tutor.next_review_task(parsed)
        except AppError as e:
            console.print(f"[yellow]{e}[/]")
            return
        outcome, _ = _solve_one(tutor, task, AttemptMode.REVIEW)
        if outcome == "exit" or not _ask_yes_no("Повторять дальше?"):
            return


# ── программы на Python (Phase 3) ───────────────────────────────────────────

CODE_VERDICT_NAMES = {
    CodeVerdict.OK: "[green]программа отработала[/]",
    CodeVerdict.WRONG_ANSWER: "[red]неверный вывод[/]",
    CodeVerdict.TIME_LIMIT: "[red]превышено время[/]",
    CodeVerdict.MEMORY_LIMIT: "[red]превышена память[/]",
    CodeVerdict.RUNTIME_ERROR: "[red]ошибка во время работы[/]",
    CodeVerdict.SYNTAX_ERROR: "[red]синтаксическая ошибка[/]",
}


def _tests_text(r: CodeRun) -> str:
    if not r.tests_total:
        return "—"
    return f"{r.tests_passed} из {r.tests_total}"


def _print_code_run(r: CodeRun) -> None:
    console.print(f"Итог: {CODE_VERDICT_NAMES[r.verdict]} · {r.duration_seconds:.2f} с")
    if r.tests_total:
        console.print(f"Тесты: {_tests_text(r)}")
    if r.failed_test is not None:
        console.print(f"[yellow]Не прошёл тест №{r.failed_test}.[/]")
    if r.stdout.strip():
        console.print(_panel(Text(r.stdout.rstrip()), title="Вывод программы", title_align="left"))
    if r.stderr.strip():
        console.print(
            _panel(Text(r.stderr.rstrip()), title="Ошибки", title_align="left", style="red")
        )
    if r.answer_guess is not None:
        console.print(f"Похоже, ответ: [bold]{escape(r.answer_guess)}[/] (последняя строка вывода)")


@app.command(name="run")
def run_code(
    task_id: Annotated[int, typer.Argument(help="ID задачи по информатике.")],
    file: Annotated[
        Path,
        typer.Argument(help="Файл с программой на Python.", exists=True, dir_okay=False),
    ],
) -> None:
    """Запустить свою программу к задаче в песочнице: тесты задачи, потом настоящие файлы."""
    try:
        code = file.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise _fail("файл с программой должен быть в кодировке UTF-8") from e
    try:
        result = _tutor().run_code(task_id, code)
    except AppError as e:
        raise _fail(str(e)) from e
    _print_code_run(result)


@app.command()
def runs(
    task_id: Annotated[int | None, typer.Option("--task", "-t", help="Только эта задача.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Сколько показать.")] = 20,
) -> None:
    """История запусков программ. Запуски никогда не удаляются."""
    found = _tutor().code_runs(task_id, limit=limit)
    if not found:
        console.print("Программы пока не запускались.")
        return
    table = _table(title="Запуски программ")
    table.add_column("№", justify="right")
    table.add_column("Когда (UTC)")
    table.add_column("Задача", justify="right")
    table.add_column("Итог")
    table.add_column("Тесты")
    table.add_column("Время, с", justify="right")
    table.add_column("Ответ?")
    for r in found:
        table.add_row(
            str(r.id),
            r.created_at.strftime("%Y-%m-%d %H:%M"),
            str(r.task_id),
            CODE_VERDICT_NAMES[r.verdict],
            _tests_text(r),
            f"{r.duration_seconds:.2f}",
            Text(r.answer_guess or "—"),
        )
    console.print(table)


# ── стартовый банк и диагностика (Phase 5) ─────────────────────────────────

FINISH_WORDS = {"закончить", "finish"}
DIAGNOSTIC_STATUS_NAMES = {
    DiagnosticStatus.ACTIVE: "идёт",
    DiagnosticStatus.FINISHED: "завершена",
    DiagnosticStatus.ABANDONED: "брошена",
}


@app.command()
def bank() -> None:
    """Загрузить стартовый банк проверенных задач (по 3 на каждый номер ЕГЭ)."""
    tutor = _tutor()
    try:
        results = tutor.install_starter_bank()
    except AppError as e:
        raise _fail(str(e)) from e
    for result in results:
        report = result.report
        duplicates = len(report.rejected_rows)
        console.print(
            f"{report.file_name}: добавлено {len(report.accepted) if result.batch else 0}"
            + (f", уже были в базе {duplicates}" if duplicates else "")
        )
    console.print(
        "[dim]Задачи стартового банка написаны ИИ (не задания ФИПИ), их ответы проверены "
        "тестами. Диагностика: ege diagnose math[/]"
    )


def _forecast_text(forecast: Forecast) -> str:
    return (
        f"{forecast.mean:.0f} из {forecast.max_points} первичных баллов "
        f"(вероятнее всего от {forecast.low:.0f} до {forecast.high:.0f})"
    )


def _print_diagnostic_state(state: DiagnosticState) -> None:
    table = _table(title=f"Диагностика: {SUBJECT_NAMES[state.session.subject]}")
    for column in ("№", "Задание", "Решу", "Уверенность", "Как получено"):
        table.add_column(column)
    for e in state.estimates:
        basis = ITEM_BASIS_NAMES[e.basis]
        if e.basis == ItemBasis.DIRECT:
            basis += f" ({e.answered} зад.)"
        if e.answer_only and e.basis == ItemBasis.DIRECT:
            basis += ", по ответу"
        table.add_row(
            str(e.exam_item), e.title, _percent(e.probability), _percent(e.confidence), basis
        )
    console.print(table)
    console.print(f"Прогноз: {_forecast_text(state.forecast)}.")
    console.print(
        "[dim]Это предварительный baseline. Тестовые баллы появятся вместе с официальной "
        "таблицей перевода. Задания части 2 оценены только по итоговому ответу.[/]"
    )


def _print_session_end(tutor: TutorApp, session: DiagnosticSession) -> None:
    if session.stop_reason is not None:
        console.print(f"Диагностика завершена: {STOP_REASON_NAMES[session.stop_reason]}.")
    _print_diagnostic_state(tutor.diagnostic_state(session.id))


@app.command()
def diagnose(
    subject: Annotated[str, typer.Argument(help=SUBJECT_HELP)],
) -> None:
    """Адаптивная диагностика: без подсказок, с таймером. Можно прервать и продолжить."""
    tutor = _tutor()
    parsed = _subject(subject)
    assert parsed is not None
    try:
        session = tutor.start_diagnostic(parsed)
    except AppError as e:
        raise _fail(str(e)) from e
    console.print(
        "[dim]Подсказок нет. Ответ на задачу даётся один раз. Команды: сдаюсь — не знаю, "
        "выход — прервать (продолжишь той же командой), закончить — завершить сейчас.[/]"
    )
    while True:
        step = tutor.diagnostic_step(session.id)
        if step.attempt is None or step.task is None:
            _print_session_end(tutor, step.session)
            return
        state = tutor.diagnostic_state(session.id)
        console.print(f"[bold]Задача {state.tasks_done + 1} (не больше {state.max_tasks})[/]")
        _show_task_header(tutor, step.task, step.attempt)
        while True:
            try:
                text = typer.prompt("Ответ", prompt_suffix=": ").strip()
            except (typer.Abort, EOFError, KeyboardInterrupt):
                console.print("\nДиагностика прервана. Продолжить: ege diagnose " + subject)
                return
            command = text.casefold()
            if command in EXIT_WORDS:
                console.print("Диагностика прервана. Продолжить: ege diagnose " + subject)
                return
            if command in FINISH_WORDS:
                _print_session_end(tutor, tutor.finish_diagnostic(session.id))
                return
            if command in GIVE_UP_WORDS:
                tutor.give_up(step.attempt.id)
                break
            if command in HINT_WORDS:
                console.print("[yellow]В диагностике подсказок нет.[/]")
                continue
            try:
                tutor.submit_answer(step.attempt.id, text)
            except AppError as e:
                console.print(f"[yellow]{e}[/]")
                continue
            break
        console.print("[dim]Ответ записан.[/]")


def _show_task_header(tutor: TutorApp, t: Task, attempt: Attempt) -> None:
    header = f"{SUBJECT_NAMES[t.subject]} · задание №{t.exam_item}"
    console.print(_panel(t.statement, title=header, title_align="left"))
    console.print(f"Источник: {_source_text(t.source)} — {t.source_ref}")
    for asset in t.assets:
        console.print(f"Файл: {asset.file_name} → {tutor.asset_path(asset)}")
    if t.answer_type == AnswerType.EXTENDED:
        console.print("[dim]Это задание части 2: введи только итоговый ответ (числа через «;»).[/]")
    console.print(f"Норматив {_minutes(attempt.time_norm_seconds)} · время пошло")


@app.command()
def diagnostics(
    session_id: Annotated[int | None, typer.Argument(help="Номер диагностики.")] = None,
    subject: Annotated[str | None, typer.Option("--subject", "-s", help=SUBJECT_HELP)] = None,
) -> None:
    """Прошлые диагностики и их итог (предварительный baseline)."""
    tutor = _tutor()
    if session_id is not None:
        try:
            _print_diagnostic_state(tutor.diagnostic_state(session_id))
        except AppError as e:
            raise _fail(str(e)) from e
        return
    sessions = tutor.diagnostic_sessions(_subject(subject))
    if not sessions:
        console.print("Диагностик ещё не было. Начать: ege diagnose math")
        return
    table = _table(title="Диагностики")
    for column in ("№", "Предмет", "Начата", "Статус", "Прогноз"):
        table.add_column(column)
    for s in sessions:
        table.add_row(
            str(s.id),
            SUBJECT_NAMES[s.subject],
            s.started_at.strftime("%d.%m.%Y %H:%M"),
            DIAGNOSTIC_STATUS_NAMES[s.status],
            _forecast_text(s.forecast) if s.forecast else "—",
        )
    console.print(table)
    console.print("Подробно: ege diagnostics НОМЕР")


def run() -> None:
    """Точка входа команды ege.

    Консоль Windows и CI-логи по умолчанию могут быть не в UTF-8; без этого русский
    текст и символы вроде «₂» роняли бы программу с UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()
