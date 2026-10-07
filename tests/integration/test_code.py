"""Программы на Python к задачам информатики (Phase 3): тесты задачи, запуски, история."""

import pytest

from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import CodeVerdict
from ege_tutor.core.ports.sandbox import RunResult, SandboxUnavailableError, SandboxVerdict
from ege_tutor.sandbox import UnavailableSandbox
from tests.fakes import LocalSandbox, ScriptedSandbox

TASKS = """
defaults:
  source: USER_MATERIAL
  source_ref: "тест"
  verification_status: REVIEWED
tasks:
  - subject: informatics
    exam_item: 17
    statement: "Найдите количество отрицательных чисел в файле numbers.txt."
    answer: 2
    assets: [numbers.txt]
    tests:
      - files: {numbers.txt: "1\\n-2\\n3\\n"}
        output: 1
      - files: {numbers.txt: "-1\\n-2\\n-3\\n"}
        output: 3
  - subject: informatics
    exam_item: 16
    statement: "Чему равно 5! ?"
    answer: 120
    tests:
      - input: "3"
        output: 6
  - subject: math
    exam_item: 6
    statement: "Решите уравнение x + 1 = 3."
    answer: 2
"""
NUMBERS = "5\n-7\n8\n-1\n"
GOOD = "print(sum(1 for x in open('numbers.txt') if int(x) < 0))"


@pytest.fixture
def make_tutor(fixed_clock):
    created = []

    def _make(sandbox) -> TutorApp:
        app = TutorApp.create(clock=fixed_clock, sandbox=sandbox)
        created.append(app)
        return app

    yield _make
    for app in created:
        app.close()


@pytest.fixture
def ids(write_file):
    write_file("numbers.txt", NUMBERS)
    return write_file("t.yaml", TASKS)


def _import(tutor: TutorApp, path) -> dict[str, int]:
    result = tutor.import_tasks(path)
    assert result.batch is not None, result.report.errors
    return {t.statement[:12]: t.id for t in tutor.tasks()}


def test_tests_are_imported_and_stored(make_tutor, ids):
    tutor = make_tutor(LocalSandbox())
    tasks = _import(tutor, ids)
    task = tutor.task(tasks["Найдите коли"])
    assert [t.output for t in task.tests] == ["1", "3"]
    assert task.tests[0].files == (("numbers.txt", "1\n-2\n3\n"),)
    assert tutor.task(tasks["Чему равно 5"]).tests[0].input == "3"


def test_good_program_passes_tests_and_suggests_answer(make_tutor, ids):
    sandbox = LocalSandbox()
    tutor = make_tutor(sandbox)
    task_id = _import(tutor, ids)["Найдите коли"]
    run = tutor.run_code(task_id, GOOD)
    assert run.verdict == CodeVerdict.OK
    assert (run.tests_passed, run.tests_total, run.failed_test) == (2, 2, None)
    assert run.answer_guess == "2"
    # тест подменяет файл задачи, основной запуск получает настоящий файл
    assert sandbox.requests[0].files["numbers.txt"] == b"1\n-2\n3\n"
    assert sandbox.requests[-1].files["numbers.txt"] == NUMBERS.encode()
    assert sandbox.requests[0].limits.network_enabled is False
    assert tutor.code_runs(task_id) == [run]


def test_wrong_program_stops_on_first_failed_test(make_tutor, ids):
    sandbox = LocalSandbox()
    tutor = make_tutor(sandbox)
    task_id = _import(tutor, ids)["Найдите коли"]
    run = tutor.run_code(task_id, "print(1)")
    assert run.verdict == CodeVerdict.WRONG_ANSWER
    assert (run.tests_passed, run.failed_test) == (1, 2)
    assert run.answer_guess is None
    assert len(sandbox.requests) == 2  # на настоящем файле не запускалась


def test_stdin_tests_and_runtime_errors(make_tutor, ids):
    tutor = make_tutor(LocalSandbox())
    task_id = _import(tutor, ids)["Чему равно 5"]
    factorial = (
        "import math, sys\nn = sys.stdin.read().strip() or '5'\nprint(math.factorial(int(n)))"
    )
    assert tutor.run_code(task_id, factorial).answer_guess == "120"
    crashed = tutor.run_code(task_id, "print(1/0)")
    assert crashed.verdict == CodeVerdict.RUNTIME_ERROR
    assert crashed.failed_test == 1
    assert "ZeroDivisionError" in crashed.stderr
    broken = tutor.run_code(task_id, "print(")
    assert broken.verdict == CodeVerdict.SYNTAX_ERROR


def test_sandbox_limits_become_verdicts(make_tutor, ids):
    slow = RunResult(SandboxVerdict.TIME_LIMIT, "", "Превышено время работы.", -9, 10.0)
    tutor = make_tutor(ScriptedSandbox(slow))
    task_id = _import(tutor, ids)["Найдите коли"]
    run = tutor.run_code(task_id, GOOD)
    assert run.verdict == CodeVerdict.TIME_LIMIT
    assert run.failed_test == 1


def test_output_comparison_ignores_spacing(make_tutor, ids):
    tutor = make_tutor(LocalSandbox())
    task_id = _import(tutor, ids)["Найдите коли"]
    spaced = GOOD.replace("print(", "print('  ', ") + "\nprint()"
    assert tutor.run_code(task_id, spaced).verdict == CodeVerdict.OK


def test_only_informatics_and_sane_programs(make_tutor, ids):
    tutor = make_tutor(LocalSandbox())
    tasks = _import(tutor, ids)
    with pytest.raises(AppError, match="только в задачах по информатике"):
        tutor.run_code(tasks["Решите уравн"], "print(2)")
    with pytest.raises(AppError, match="пустая"):
        tutor.run_code(tasks["Найдите коли"], "   ")
    with pytest.raises(AppError, match="100 000"):
        tutor.run_code(tasks["Найдите коли"], "#" * 100_001)
    with pytest.raises(AppError, match="не найдена"):
        tutor.run_code(9999, "print(1)")
    assert tutor.code_runs() == []


def test_unavailable_sandbox_is_reported_honestly(make_tutor, ids):
    tutor = make_tutor(UnavailableSandbox("нет Docker"))
    task_id = _import(tutor, ids)["Найдите коли"]
    with pytest.raises(AppError, match="песочница для программ не настроена"):
        tutor.run_code(task_id, GOOD)

    class Broken(ScriptedSandbox):
        def run(self, request):
            raise SandboxUnavailableError("runner не отвечает")

    tutor = make_tutor(Broken())
    task_id = tutor.tasks()[0].id
    with pytest.raises(AppError, match="runner не отвечает"):
        tutor.run_code(task_id, GOOD)


def test_runs_are_linked_to_attempts(make_tutor, ids):
    tutor = make_tutor(LocalSandbox())
    task_id = _import(tutor, ids)["Найдите коли"]
    attempt = tutor.start_attempt(task_id)
    run = tutor.run_code(task_id, GOOD, attempt.id)
    assert tutor.code_runs(attempt_id=attempt.id) == [run]
    assert tutor.code_run(run.id) == run
    other = tutor.tasks()[0].id if tutor.tasks()[0].id != task_id else tutor.tasks()[1].id
    with pytest.raises(AppError, match="не относится"):
        tutor.run_code(other, GOOD, attempt.id)
    tutor.submit_answer(attempt.id, run.answer_guess)
    assert tutor.attempt(attempt.id).correct
    with pytest.raises(AppError, match="уже завершена"):
        tutor.run_code(task_id, GOOD, attempt.id)
    with pytest.raises(AppError, match="не найден"):
        tutor.code_run(9999)


def test_import_rejects_bad_tests(tutor, write_file):
    bad = """
defaults: {source: USER_MATERIAL, source_ref: "тест"}
tasks:
  - {subject: math, exam_item: 6, statement: "a", answer: 1, tests: [{input: "1", output: 1}]}
  - {subject: informatics, exam_item: 16, statement: "b", answer: 1, tests: "1 -> 1"}
  - {subject: informatics, exam_item: 16, statement: "c", answer: 1, tests: [{input: "1"}]}
  - {subject: informatics, exam_item: 16, statement: "d", answer: 1,
     tests: [{output: 1, files: {"../x.txt": "1"}}]}
  - {subject: informatics, exam_item: 16, statement: "e", answer: 1, tests: [{output: " "}]}
  - {subject: informatics, exam_item: 16, statement: "f", answer: 1,
     tests: [{output: 1, stdin: "1"}]}
"""
    report = tutor.preview_import(write_file("bad.yaml", bad))
    assert not report.accepted
    messages = [e.message for e in report.errors]
    assert any("только у задач по информатике" in m for m in messages)
    assert any("нужен список" in m for m in messages)
    assert any("нужно поле output" in m for m in messages)
    assert any("недопустимое имя файла" in m for m in messages)
    assert any("пустой output" in m for m in messages)
    assert any("неизвестные поля stdin" in m for m in messages)
