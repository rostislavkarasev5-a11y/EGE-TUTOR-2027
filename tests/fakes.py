"""Заменители портов для тестов."""

import subprocess
import sys
import tempfile
from pathlib import Path

from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxVerdict


class LocalSandbox:
    """Запускает программу обычным Python без ограничений. Только для тестов CORE:

    работает и на Windows, где настоящий движок песочницы недоступен.
    """

    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    @property
    def is_available(self) -> bool:
        return True

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in request.files.items():
                (Path(tmp) / name).write_bytes(content)
            done = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", request.code],
                input=request.stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=tmp,
                timeout=30,
                check=False,
            )
        if "SyntaxError" in done.stderr:
            verdict = SandboxVerdict.SYNTAX_ERROR
        elif done.returncode != 0:
            verdict = SandboxVerdict.RUNTIME_ERROR
        else:
            verdict = SandboxVerdict.OK
        return RunResult(verdict, done.stdout, done.stderr, done.returncode, 0.01)


class ScriptedSandbox:
    """Возвращает заранее заданные результаты по очереди."""

    def __init__(self, *results: RunResult, available: bool = True) -> None:
        self.results = list(results)
        self.available = available
        self.requests: list[RunRequest] = []

    @property
    def is_available(self) -> bool:
        return self.available

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        return self.results.pop(0)
