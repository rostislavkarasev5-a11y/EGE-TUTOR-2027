"""CLI на Typer. Только ввод/вывод: вся логика — в TutorApp."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ege_tutor import __version__
from ege_tutor.config import ConfigError
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    SOURCE_LABELS,
    AnswerKind,
    ImportBatchStatus,
    ImportReport,
    Subject,
    TaskSource,
)
from ege_tutor.core.services.catalog import CatalogError

SUBJECT_NAMES = {
    Subject.MATH_PROFILE: "Математика (профиль)",
    Subject.INFORMATICS: "Информатика",
}
SUBJECT_HELP = "Предмет: math или informatics."

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

    exams = Table(title="Экзамены")
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

    parts = Table(title="Компоненты")
    parts.add_column("Компонент")
    parts.add_column("Статус")
    parts.add_row("Хранилище (Phase 1)", _yes_no(state.storage_ready))
    parts.add_row("Python Sandbox (Phase 3)", _yes_no(state.sandbox_available))
    parts.add_row("AI Layer (Phase 6)", _yes_no(state.ai_available))
    console.print(parts)
    console.print(f"Задач в базе: {state.task_count}")


@app.command()
def init() -> None:
    """Создать или обновить локальную базу данных. Безопасно запускать повторно."""
    tutor = _tutor()
    console.print(f"[green]База готова:[/] {tutor.settings.data_dir}")


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

    table = Table(title="Профиль")
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
    table = Table(title=f"{SUBJECT_NAMES[parsed]}, ЕГЭ {spec.exam_year} ({spec.status})")
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
        table = Table(title=SUBJECT_NAMES[subj])
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
        table = Table(title=title, title_style=style)
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
    table = Table(title="Импорты")
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
    table = Table(title="Задачи")
    table.add_column("ID", justify="right")
    table.add_column("Предмет")
    table.add_column("№", justify="right")
    table.add_column("Условие")
    table.add_column("Источник")
    for t in found:
        statement = " ".join(t.statement.split())
        short = statement if len(statement) <= 60 else statement[:57] + "..."
        table.add_row(
            str(t.id),
            SUBJECT_NAMES[t.subject],
            str(t.exam_item),
            short,
            _source_text(t.source),
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
    console.print(Panel(t.statement, title=header, title_align="left"))
    console.print(f"Источник: {_source_text(t.source)} — {t.source_ref}")
    if t.source_version:
        console.print(f"Версия источника: {t.source_version}")
    console.print(f"Проверка: {t.verification_status}")
    if t.skills:
        console.print(f"Навыки: {', '.join(t.skills)}")
    for asset in t.assets:
        console.print(f"Файл: {asset.file_name} → {tutor.asset_path(asset)}")
    if show_answer:
        console.print(f"Ответ: [bold]{t.answer or '—'}[/]")
        if t.solution:
            console.print(Panel(t.solution, title="Решение", title_align="left"))


def run() -> None:
    """Точка входа команды ege.

    Консоль Windows и CI-логи по умолчанию могут быть не в UTF-8; без этого русский
    текст и символы вроде «₂» роняли бы программу с UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()
