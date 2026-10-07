"""Команда ege-web: запустить сайт и задать пароль владельца (ADR-0013)."""

import os
import sys
from typing import Annotated

import typer

from ege_tutor.config import ConfigError, load_settings
from ege_tutor.interfaces.web.auth import MIN_PASSWORD_LENGTH, PasswordStore, web_dir

INSECURE_ENV = "EGE_WEB_INSECURE_COOKIES"

app = typer.Typer(
    help="Сайт EGE-TUTOR-2027.",
    no_args_is_help=True,
    add_completion=False,
)


def _password_store() -> PasswordStore:
    try:
        settings = load_settings()
    except ConfigError as e:
        typer.echo(f"Ошибка конфигурации: {e}", err=True)
        raise typer.Exit(code=1) from e
    return PasswordStore(web_dir(settings.data_dir) / "password.argon2")


@app.command(name="set-password")
def set_password() -> None:
    """Задать или сменить пароль для входа на сайт."""
    store = _password_store()
    while True:
        password = typer.prompt(
            f"Новый пароль (не короче {MIN_PASSWORD_LENGTH} символов)",
            hide_input=True,
            confirmation_prompt="Повтори пароль",
        )
        try:
            store.set(password)
        except ValueError as e:
            typer.echo(f"Не подходит: {e}")
            continue
        break
    typer.echo("Пароль сохранён. Войти на сайт можно с ним.")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Адрес, на котором слушать.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Порт.")] = 8000,
    insecure_cookies: Annotated[
        bool,
        typer.Option(
            "--insecure-cookies",
            help="Разрешить вход без https (только для проверки на своём компьютере).",
        ),
    ] = False,
) -> None:
    """Запустить сайт. На сервере его закрывает Caddy с https."""
    import uvicorn

    from ege_tutor.core.app import TutorApp
    from ege_tutor.interfaces.web.app import create_app

    if not _password_store().is_set():
        typer.echo("Сначала задай пароль: ege-web set-password", err=True)
        raise typer.Exit(code=1)
    insecure = insecure_cookies or os.environ.get(INSECURE_ENV) == "1"
    tutor = TutorApp.create()
    try:
        uvicorn.run(
            create_app(tutor, secure_cookies=not insecure),
            host=host,
            port=port,
            proxy_headers=True,
            forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
            server_header=False,
        )
    finally:
        tutor.close()


def run() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    app()
