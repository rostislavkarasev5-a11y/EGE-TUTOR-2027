"""Команды CLI Phase 1. Каждый тест работает со своей временной базой (conftest)."""

import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from ege_tutor.core.app import TutorApp
from ege_tutor.core.domain import Subject
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


# ── Phase 2: решение задач ──────────────────────────────────────────────────


def _import_and_review_all():
    invoke("import", SAMPLE, "--apply")
    result = runner.invoke(app, ["review"], input="да\n" * 5)
    assert result.exit_code == 0, result.output
    assert "Непроверенных задач нет" in result.output


def test_solve_requires_review_first():
    invoke("import", SAMPLE, "--apply")
    result = invoke("solve")
    assert result.exit_code == 1
    assert "review" in result.output


def test_solve_correct_answer_then_stop():
    _import_and_review_all()
    result = runner.invoke(app, ["solve", "1"], input="6\nнет\n")
    assert result.exit_code == 0, result.output
    assert "верно" in result.output
    assert "Решено самостоятельно" in result.output
    assert "не задание ФИПИ" in result.output  # метка источника видна при решении


def test_solve_hint_wrong_retry_and_history():
    _import_and_review_all()
    result = runner.invoke(app, ["solve", "2"], input="?\n2/5\nда\n0,4\nнет\n")
    assert result.exit_code == 0, result.output
    assert "Уровень 1" in result.output
    assert "неверный формат" in result.output
    assert "Подсказки из прошлой попытки учтены" in result.output
    history = invoke("attempts")
    assert "2/5" in history.output
    assert "0,4" in history.output


def test_solve_give_up_shows_answer_with_comma():
    _import_and_review_all()
    result = runner.invoke(app, ["solve", "2"], input="сдаюсь\nнет\n")
    assert result.exit_code == 0, result.output
    assert "Правильный ответ: 0,4" in result.output
    assert "сдался" in invoke("attempts").output


def test_solve_exit_keeps_abandoned_attempt():
    _import_and_review_all()
    result = runner.invoke(app, ["solve", "1"], input="выход\n")
    assert result.exit_code == 0, result.output
    assert "брошена" in invoke("attempts").output


def test_solve_interrupted_input_is_saved_as_abandoned():
    _import_and_review_all()
    result = runner.invoke(app, ["solve", "1"], input="")
    assert "прервана" in result.output
    assert "брошена" in invoke("attempts").output


def test_review_no_marks_task_disputed():
    invoke("import", SAMPLE, "--apply")
    result = runner.invoke(app, ["review", "1"], input="нет\n")
    assert result.exit_code == 0, result.output
    assert "спорная" in invoke("tasks").output


def test_review_asks_again_on_unknown_input():
    # Пользователь по ошибке ввёл команду вместо ответа — проверка не должна молча закончиться.
    invoke("import", SAMPLE, "--apply")
    result = runner.invoke(app, ["review", "1"], input="ege solve\nда\n")
    assert result.exit_code == 0, result.output
    assert "Не понял ответ" in result.output
    assert "Задача 1 проверена" in result.output


def test_review_skip_ends_with_message():
    invoke("import", SAMPLE, "--apply")
    result = runner.invoke(app, ["review"], input="пропустить\n")
    assert result.exit_code == 0, result.output
    assert "пропущена" in result.output


def test_run_program_through_runner(tmp_path, monkeypatch):
    """ege run: настоящий runner на Unix-сокете, задача-пример с тестами (Phase 3)."""
    import socket
    import threading
    import time

    from ege_tutor.sandbox import RUNNER_SOCKET_ENV
    from ege_tutor.sandbox import runner as sandbox_runner

    if not sys.platform.startswith("linux") or not hasattr(socket, "AF_UNIX"):
        pytest.skip("песочница работает только на Linux")
    sock = tmp_path / "runner.sock"
    threading.Thread(
        target=lambda: CliRunner().invoke(sandbox_runner.app, ["serve", "--socket", str(sock)]),
        daemon=True,
    ).start()
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.05)
    monkeypatch.setenv(RUNNER_SOCKET_ENV, str(sock))

    assert invoke("import", SAMPLE, "--apply").exit_code == 0
    tutor = TutorApp.create()
    task = next(t for t in tutor.tasks() if t.exam_item == 17)
    math_task = next(t for t in tutor.tasks() if t.subject == Subject.MATH_PROFILE)
    tutor.close()
    assert len(task.tests) == 2

    program = tmp_path / "solution.py"
    program.write_text(
        "a = [int(x) for x in open('numbers.txt')]\n"
        "print(sum((x < 0) != (y < 0) for x, y in zip(a, a[1:])))\n",
        encoding="utf-8",
    )
    result = invoke("run", str(task.id), str(program))
    assert result.exit_code == 0, result.output
    assert "программа отработала" in result.output
    assert "2 из 2" in result.output
    assert "Похоже, ответ: 3" in result.output

    program.write_text("print(0)\n", encoding="utf-8")
    result = invoke("run", str(task.id), str(program))
    assert "неверный вывод" in result.output
    assert "Не прошёл тест №1" in result.output

    history = invoke("runs", "--task", str(task.id))
    assert history.exit_code == 0
    assert "2 из 2" in history.output
    assert invoke("run", str(math_task.id), str(program)).exit_code == 1


def test_mastery_mistakes_queue_and_repeat():
    """Phase 4: освоение, ошибки, уточнение причины, очередь и повторение."""
    _import_and_review_all()
    assert "Пока нет решённых задач" in invoke("mastery", "--by", "skill").output
    wrong = runner.invoke(app, ["solve", "1"], input="-6\nнет\n")
    assert wrong.exit_code == 0, wrong.output
    assert "Ошибка записана: невнимательность" in wrong.output

    by_item = invoke("mastery", "-s", "math")
    assert by_item.exit_code == 0, by_item.output
    assert "Освоение" in by_item.output and "Mastery v0" in by_item.output
    assert "M06" in invoke("mastery", "--by", "skill").output
    assert invoke("mastery", "--by", "topic").exit_code == 0
    assert "Brier" in invoke("mastery", "--calibration").output
    assert invoke("mastery", "--by", "nonsense").exit_code == 1

    history = invoke("mistakes")
    assert "Частые ошибки" in history.output and "невнимательность" in history.output
    fixed = invoke("mistake", "1", "condition")
    assert fixed.exit_code == 0, fixed.output
    assert "непонимание условия" in fixed.output
    assert invoke("mistake", "1", "formula").exit_code == 1  # уже уточнена
    assert invoke("mistake", "2", "nonsense").exit_code == 1

    queue = invoke("queue")
    assert "Очередь повторений" in queue.output
    repeat = runner.invoke(app, ["repeat"], input="6\nнет\n")
    assert repeat.exit_code == 0, repeat.output
    assert "верно" in repeat.output
    assert "REVIEW" not in repeat.output  # режим не показывается как код
    assert "Пересчитано навыков" in invoke("recalc").output


def test_bank_and_diagnostic():
    """Phase 5: стартовый банк, диагностика с паузой и итог."""
    assert "ege diagnose" in invoke("diagnostics").output  # ещё не было
    loaded = invoke("bank")
    assert loaded.exit_code == 0, loaded.output
    assert "math_profile.yaml: добавлено 57" in loaded.output
    assert "уже были в базе 57" in invoke("bank").output

    paused = runner.invoke(app, ["diagnose", "math"], input="?\n0\nсдаюсь\nвыход\n")
    assert paused.exit_code == 0, paused.output
    assert "подсказок нет" in paused.output and "Задача 3" in paused.output
    assert "Продолжить: ege diagnose math" in paused.output

    finished = runner.invoke(app, ["diagnose", "math"], input="закончить\n")
    assert finished.exit_code == 0, finished.output
    assert "ты завершил диагностику сам" in finished.output
    assert "Прогноз:" in finished.output and "выведено косвенно" in finished.output
    history = invoke("diagnostics")
    assert "завершена" in history.output
    assert "Прогноз" in invoke("diagnostics", "1").output
    assert invoke("diagnostics", "99").exit_code == 1
