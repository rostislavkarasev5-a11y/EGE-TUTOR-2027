"""Запуск программ на Python к задачам информатики (Phase 3, архитектура, раздел 9).

Правила:
- запускать можно только программы к задачам по информатике;
- программа получает файлы задачи (по их именам) в рабочей папке;
- сначала программа проходит тест-кейсы задачи: маленькие примеры с известным ответом
  (свой stdin и/или короткие версии файлов задачи); на первом непройденном тесте
  проверка останавливается;
- если тесты пройдены (или их нет), программа запускается на настоящих файлах задачи,
  и последняя непустая строка вывода предлагается как ответ к заданию;
- каждый запуск записывается навсегда; ответ отправляет сам пользователь, Sandbox
  ничего не решает за CORE.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ege_tutor.config import SandboxConfig
from ege_tutor.core.domain import (
    AttemptStatus,
    CodeRun,
    CodeVerdict,
    Subject,
    Task,
    TaskAsset,
    TaskTestCase,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository
from ege_tutor.core.ports.sandbox import (
    RunRequest,
    RunResult,
    Sandbox,
    SandboxLimits,
    SandboxUnavailableError,
    SandboxVerdict,
)

MAX_CODE_CHARS = 100_000
MAX_FILES_BYTES = 40 * 1024 * 1024  # запрос к песочнице не больше 64 МБ вместе с base64
_STORED_OUTPUT_CHARS = 20_000


def outputs_match(actual: str, expected: str) -> bool:
    """Вывод совпадает с ожидаемым: пробелы и переносы строк между значениями не важны."""
    return actual.split() == expected.split()


def _clip(text: str) -> str:
    if len(text) <= _STORED_OUTPUT_CHARS:
        return text
    return text[:_STORED_OUTPUT_CHARS] + "\n… (обрезано)"


@dataclass(frozen=True)
class _Outcome:
    verdict: CodeVerdict
    passed: int
    failed_test: int | None
    result: RunResult


class CodeService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        sandbox: Sandbox,
        config: SandboxConfig,
        asset_path: Callable[[TaskAsset], Path],
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._sandbox = sandbox
        self._config = config
        self._asset_path = asset_path

    def _limits(self) -> SandboxLimits:
        return SandboxLimits(
            time_limit_seconds=self._config.time_limit_seconds,
            memory_limit_mb=self._config.memory_limit_mb,
            network_enabled=False,  # сеть программам не нужна (раздел 9)
        )

    def _files(self, task: Task) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        total = 0
        for asset in task.assets:
            path = self._asset_path(asset)
            try:
                content = path.read_bytes()
            except OSError as e:
                raise AppError(f"не удалось прочитать файл задачи {asset.file_name}: {e}") from e
            total += len(content)
            if total > MAX_FILES_BYTES:
                raise AppError("файлы задачи больше 40 МБ: такую программу запускать долго")
            files[asset.file_name] = content
        return files

    def _run(self, code: str, stdin: str, files: dict[str, bytes]) -> RunResult:
        request = RunRequest(code=code, stdin=stdin, files=files, limits=self._limits())
        try:
            return self._sandbox.run(request)
        except SandboxUnavailableError as e:
            raise AppError(f"песочница недоступна: {e}") from e

    def _check(
        self, code: str, tests: tuple[TaskTestCase, ...], files: dict[str, bytes]
    ) -> _Outcome:
        passed = 0
        for test in tests:
            test_files = files | {name: content.encode("utf-8") for name, content in test.files}
            result = self._run(code, test.input, test_files)
            if result.verdict != SandboxVerdict.OK:
                return _Outcome(CodeVerdict(result.verdict.value), passed, test.position, result)
            if not outputs_match(result.stdout, test.output):
                return _Outcome(CodeVerdict.WRONG_ANSWER, passed, test.position, result)
            passed += 1
        result = self._run(code, "", files)
        return _Outcome(CodeVerdict(result.verdict.value), passed, None, result)

    def run(self, task_id: int, code: str, attempt_id: int | None = None) -> CodeRun:
        """Проверить программу на тестах задачи, запустить её и записать результат."""
        task = self._repo.get_task(task_id)
        if task is None:
            raise AppError(f"задача №{task_id} не найдена")
        if task.subject != Subject.INFORMATICS:
            raise AppError("программы на Python запускаются только в задачах по информатике")
        if not code.strip():
            raise AppError("программа пустая")
        if len(code) > MAX_CODE_CHARS:
            raise AppError("программа длиннее 100 000 символов")
        if attempt_id is not None:
            attempt = self._repo.get_attempt(attempt_id)
            if attempt is None or attempt.task_id != task_id:
                raise AppError(f"попытка №{attempt_id} не относится к задаче №{task_id}")
            if attempt.status != AttemptStatus.IN_PROGRESS:
                raise AppError("эта попытка уже завершена")
        if not self._sandbox.is_available:
            raise AppError(
                "песочница для программ не настроена: на сервере это контейнер runner, "
                "на компьютере — Docker Desktop (см. README)"
            )

        outcome = self._check(code, task.tests, self._files(task))
        return self._repo.add_code_run(
            task_id=task_id,
            attempt_id=attempt_id,
            created_at=self._clock.now(),
            code=code,
            verdict=outcome.verdict,
            tests_total=len(task.tests),
            tests_passed=outcome.passed,
            failed_test=outcome.failed_test,
            stdout=_clip(outcome.result.stdout),
            stderr=_clip(outcome.result.stderr),
            exit_code=outcome.result.exit_code,
            duration_seconds=outcome.result.duration_seconds,
        )

    def runs(
        self, task_id: int | None = None, attempt_id: int | None = None, limit: int = 20
    ) -> list[CodeRun]:
        return self._repo.list_code_runs(task_id, attempt_id, limit)
