"""Команды CLI Phase 1. Каждый тест работает со своей временной базой (conftest)."""

import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from ege_tutor.interfaces.cli.main import app
from tests.conftest import REPO_ROOT

runner = CliRunner()
SAMPLE = str(REPO_ROOT / "content" / "sample" / "tasks.yaml")


def invoke(*args: str):
    return runner.invoke(app, list(args))


def test_init_creates_database(data_dir):
    result = invoke("init")
    assert result.exit_code == 0, result.output
    assert (data_dir / "ege.db").is_file()


def test_exam_shows_structure():
    result = invoke("exam", "math")
    assert result.exit_code == 0, result.output
    assert "32" in result.output
    assert invoke("exam", "inf").exit_code == 0
    assert invoke("exam", "physics").exit_code == 1


@pytest.mark.parametrize("subject", ["math", "informatics", "MATH_PROFILE"])
def test_topics(subject):
    result = invoke("topics", "--subject", subject, "--skills")
    assert result.exit_code == 0, result.output


def test_profile_show_and_update():
    result = invoke("profile", "--target-math", "95")
    assert result.exit_code == 0, result.output
    assert "95" in result.output
    assert invoke("profile", "--target-informatics", "150").exit_code == 1


def test_import_preview_then_apply_then_undo():
    preview = invoke("import", SAMPLE)
    assert preview.exit_code == 0, preview.output
    assert "--apply" in preview.output
    assert "Задач не найдено" in invoke("tasks").output

    applied = invoke("import", SAMPLE, "--apply")
    assert applied.exit_code == 0, applied.output
    listed = invoke("tasks", "--source", "ai_generated")
    assert "не задание ФИПИ" in listed.output

    assert "действует" in invoke("imports").output
    assert invoke("undo-import", "1").exit_code == 0
    assert invoke("undo-import", "1").exit_code == 1
    assert "Задач не найдено" in invoke("tasks").output


def test_task_always_shows_source_and_hides_answer_by_default():
    invoke("import", SAMPLE, "--apply")
    shown = invoke("task", "1")
    assert shown.exit_code == 0, shown.output
    assert "Сгенерировано ИИ" in shown.output
    assert "Ответ" not in shown.output
    assert "Ответ" in invoke("task", "1", "--answer").output
    assert invoke("task", "999").exit_code == 1


def test_import_of_broken_file_fails(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("x", encoding="utf-8")
    result = invoke("import", str(bad))
    assert result.exit_code == 1
    assert "неподдерживаемый формат" in result.output


def test_cli_survives_non_utf8_console():
    """В Windows-консоли и CI вывод может быть не в UTF-8: русский текст не должен ронять CLI."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ege_tutor.interfaces.cli.main import run; run()",
            "exam",
            "math",
        ],
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert "ЕГЭ".encode() in result.stdout


def _box_chars(text: str) -> set[str]:
    return {ch for ch in text if 0x2500 <= ord(ch) <= 0x257F}


@pytest.mark.parametrize(
    "args",
    [["info"], ["profile"], ["exam", "math"], ["topics", "--skills"], ["imports"], ["tasks"]],
)
def test_table_lines_fit_old_windows_console(args):
    """Линии таблиц должны быть из кодовой страницы cp866: их рисуют старые шрифты консоли."""
    invoke("import", SAMPLE, "--apply")
    result = invoke(*args)
    assert result.exit_code == 0, result.output
    for ch in _box_chars(result.output):
        ch.encode("cp866")  # UnicodeEncodeError → такую линию консоль покажет как «?»


def test_task_panel_fits_old_windows_console():
    invoke("import", SAMPLE, "--apply")
    result = invoke("task", "1", "--answer")
    assert result.exit_code == 0, result.output
    assert _box_chars(result.output)
    for ch in _box_chars(result.output):
        ch.encode("cp866")
