"""Команда ege-web: пароль и запуск без пароля."""

from typer.testing import CliRunner

from ege_tutor.config import load_settings
from ege_tutor.interfaces.web.auth import PasswordStore, load_secret_key, web_dir
from ege_tutor.interfaces.web.cli import app

runner = CliRunner()


def _store() -> PasswordStore:
    return PasswordStore(web_dir(load_settings().data_dir) / "password.argon2")


def test_set_password_asks_twice_and_rejects_short():
    result = runner.invoke(
        app, ["set-password"], input="short\nshort\nдлинный-пароль\nдлинный-пароль\n"
    )
    assert result.exit_code == 0, result.output
    assert "не короче" in result.output
    assert _store().verify("длинный-пароль")


def test_serve_refuses_without_password():
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "set-password" in result.output


def test_secret_key_is_created_once(tmp_path, monkeypatch):
    monkeypatch.delenv("EGE_WEB_SECRET_KEY", raising=False)
    first = load_secret_key(tmp_path)
    assert len(first) > 40
    assert load_secret_key(tmp_path) == first


def test_secret_key_from_environment(tmp_path, monkeypatch):
    value = "k" * 50
    monkeypatch.setenv("EGE_WEB_SECRET_KEY", value)
    assert load_secret_key(tmp_path) == value
    assert not (tmp_path / "web" / "secret.key").exists()
