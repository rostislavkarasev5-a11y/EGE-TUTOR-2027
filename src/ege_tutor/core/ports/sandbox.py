from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SandboxVerdict(StrEnum):
    """Итог запуска программы в sandbox (проверка ответа — отдельный шаг CORE)."""

    OK = "OK"
    TIME_LIMIT = "TIME_LIMIT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"


@dataclass(frozen=True)
class SandboxLimits:
    time_limit_seconds: float
    memory_limit_mb: int
    network_enabled: bool = False


@dataclass(frozen=True)
class RunRequest:
    code: str
    limits: SandboxLimits
    stdin: str = ""
    files: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    verdict: SandboxVerdict
    stdout: str
    stderr: str
    exit_code: int | None
    duration_seconds: float


class SandboxUnavailableError(RuntimeError):
    """Sandbox не настроен или не реализован в текущей фазе."""


@runtime_checkable
class Sandbox(Protocol):
    """Изолированный запуск Python-кода пользователя (реализация — Phase 3, ADR-0008).

    Ограничения: время, CPU, RAM, процессы, файловая система; сеть по умолчанию выключена.
    """

    @property
    def is_available(self) -> bool: ...

    def run(self, request: RunRequest) -> RunResult: ...
