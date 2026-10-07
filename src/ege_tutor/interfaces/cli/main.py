"""CLI на Typer. Только ввод/вывод: вся логика — в TutorApp."""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ege_tutor import __version__
from ege_tutor.config import ConfigError
from ege_tutor.core.app import TutorApp
from ege_tutor.core.domain import Subject

SUBJECT_NAMES = {
    Subject.MATH_PROFILE: "Математика (профиль)",
    Subject.INFORMATICS: "Информатика",
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


def _yes_no(value: bool) -> str:
    return "[green]готово[/]" if value else "[yellow]ещё нет[/]"


@app.command()
def info() -> None:
    """Состояние программы: фаза, даты экзаменов, доступные компоненты."""
    try:
        tutor = TutorApp.create()
    except ConfigError as e:
        console.print(f"[red]Ошибка конфигурации:[/] {e}")
        raise typer.Exit(code=1) from e
    state = tutor.info()

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
