"""Smoke-тесты: проект импортируется, конфигурация грузится, приложение собирается."""

from typer.testing import CliRunner

import ege_tutor
from ege_tutor.config import load_settings
from ege_tutor.core import ports
from ege_tutor.core.app import TutorApp
from ege_tutor.interfaces.cli.main import app


def test_package_imports_and_has_version():
    assert ege_tutor.__version__ != "0.0.0+unknown"


def test_default_config_loads():
    settings = load_settings()
    assert settings.app.app.name == "EGE-TUTOR-2027"
    assert settings.mastery.model_version == "v0"
    assert settings.diagnostics.rules.hints_allowed is False


def test_tutor_app_creates_with_defaults(data_dir):
    tutor = TutorApp.create()
    info = tutor.info()
    assert info.phase == 1
    assert not info.ai_available
    assert not info.sandbox_available
    assert info.storage_ready
    assert info.task_count == 0
    assert (data_dir / "ege.db").is_file()


def test_ports_exist():
    for name in ("Repository", "AIService", "Sandbox", "Clock"):
        assert hasattr(ports, name)


def test_cli_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert ege_tutor.__version__ in result.output


def test_cli_info():
    result = CliRunner().invoke(app, ["info"])
    assert result.exit_code == 0, result.output
    assert "TBD" in result.output
