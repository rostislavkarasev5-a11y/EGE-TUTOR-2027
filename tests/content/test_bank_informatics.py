"""Проверка стартового банка задач по информатике (ADR-0016).

Каждая задача банка — AI_GENERATED и получает REVIEWED только потому, что здесь:
- эталонная программа к задаче выдаёт ответ из YAML на настоящих файлах задачи;
- та же программа проходит тест-кейсы задачи (tests);
- файлы к задачам заново генерируются скриптом make_files.py и совпадают побайтно;
- файл банка импортируется без ошибок.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.conftest import REPO_ROOT

BANK = REPO_ROOT / "content" / "bank" / "informatics.yaml"
BANK_DIR = BANK.parent / "informatics"
SOLUTIONS = BANK_DIR / "solutions"
FILES = BANK_DIR / "files"
RUN_TIMEOUT = 20  # секунд на один запуск; на CI с Windows программы работают медленнее

REF_PATTERN = re.compile(r"^EGE-TUTOR-2027, стартовый банк: информатика №(\d+), задача ([123])$")


def _load() -> dict:
    with BANK.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


DATA = _load()
DEFAULTS = DATA.get("defaults") or {}
TASKS = [{**DEFAULTS, **task} for task in DATA["tasks"]]


def _solution(task: dict) -> Path:
    number = task["difficulty"] - 1  # сложность 2, 3, 4 → задача 1, 2, 3
    return SOLUTIONS / f"i{task['exam_item']:02d}_{number}.py"


def _last_line(output: str) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _run(solution: Path, workdir: Path, stdin: str = "") -> str:
    result = subprocess.run(
        [sys.executable, "-I", str(solution)],
        cwd=workdir,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=RUN_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, f"{solution.name} завершилась с ошибкой:\n{result.stderr}"
    return result.stdout


def _copy_assets(task: dict, workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    for asset in task.get("assets") or []:
        source = BANK.parent / asset
        shutil.copyfile(source, workdir / source.name)


def test_bank_structure():
    assert len(TASKS) == 81
    refs = [task["source_ref"] for task in TASKS]
    assert len(set(refs)) == len(refs), "source_ref должен быть уникальным"
    by_item: dict[int, list[int]] = {}
    for task in TASKS:
        assert task["subject"] == "informatics"
        assert task["source"] == "AI_GENERATED"
        assert task["verification_status"] == "REVIEWED"
        match = REF_PATTERN.match(task["source_ref"])
        assert match, task["source_ref"]
        assert int(match.group(1)) == task["exam_item"]
        assert int(match.group(2)) == task["difficulty"] - 1
        for field in ("statement", "answer", "solution", "hints", "time_norm_minutes", "skills"):
            assert task.get(field) not in (None, "", []), f"{task['source_ref']}: нет {field}"
        assert 2 <= len(task["hints"]) <= 3, task["source_ref"]
        assert 1 <= len(task["skills"]) <= 2, task["source_ref"]
        by_item.setdefault(task["exam_item"], []).append(task["difficulty"])
    assert sorted(by_item) == list(range(1, 28))
    assert all(sorted(levels) == [2, 3, 4] for levels in by_item.values()), by_item


def test_every_task_has_solution_and_vice_versa():
    expected = {_solution(task).name for task in TASKS}
    actual = {path.name for path in SOLUTIONS.glob("*.py")}
    assert expected == actual


def test_file_based_tasks_have_tests():
    for task in TASKS:
        if task.get("assets") or task["exam_item"] in {17, 24, 25, 26, 27}:
            assert 1 <= len(task.get("tests") or []) <= 2, task["source_ref"]


@pytest.mark.parametrize("task", TASKS, ids=[_solution(t).stem for t in TASKS])
def test_reference_solution_gives_answer(task: dict, tmp_path: Path):
    solution = _solution(task)
    workdir = tmp_path / "run"
    _copy_assets(task, workdir)
    output = _run(solution, workdir)
    assert _last_line(output).split() == str(task["answer"]).split()

    # Тест-кейсы задачи: короткие файлы заменяют настоящие, input подаётся на stdin.
    for position, case in enumerate(task.get("tests") or [], start=1):
        case_dir = tmp_path / f"case{position}"
        _copy_assets(task, case_dir)
        for name, content in (case.get("files") or {}).items():
            (case_dir / name).write_bytes(str(content).encode("utf-8"))
        output = _run(solution, case_dir, str(case.get("input") or ""))
        expected = str(case["output"]).split()
        assert output.split() == expected, f"тест {position}: {output!r} вместо {expected}"


def test_files_are_reproducible(tmp_path: Path):
    out = tmp_path / "files"
    subprocess.run(
        [sys.executable, "-I", str(BANK_DIR / "make_files.py"), "--out", str(out)],
        check=True,
        timeout=60,
    )
    generated = {path.name: path.read_bytes() for path in out.iterdir()}
    committed = {path.name: path.read_bytes() for path in FILES.iterdir()}
    assert sorted(generated) == sorted(committed)
    for name, content in generated.items():
        assert content == committed[name], f"{name} отличается от сгенерированного"
        assert b"\r" not in content, f"{name}: переводы строк должны быть LF"
        assert len(content) < 200 * 1024, f"{name} больше 200 КБ"
    assert sum(map(len, committed.values())) < 3 * 1024 * 1024


def test_every_asset_is_used():
    used = {Path(asset).name for task in TASKS for asset in task.get("assets") or []}
    assert used == {path.name for path in FILES.iterdir()}


def test_bank_imports_cleanly(tutor):
    # обычный импорт не пускает задачи от ИИ со статусом REVIEWED — только стартовый банк
    assert tutor.preview_import(BANK).accepted == []
    report = tutor.preview_import(BANK, starter_bank=True)
    assert report.errors == []
    assert report.warnings == []
    assert len(report.accepted) == 81
    assert report.rejected_rows == set()
