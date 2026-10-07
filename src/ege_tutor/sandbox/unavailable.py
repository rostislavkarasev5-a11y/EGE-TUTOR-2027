from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxUnavailableError


class UnavailableSandbox:
    """Sandbox не настроен: любой запуск честно сообщает почему."""

    def __init__(self, reason: str = "Python Sandbox не настроен") -> None:
        self.reason = reason

    @property
    def is_available(self) -> bool:
        return False

    def run(self, request: RunRequest) -> RunResult:
        raise SandboxUnavailableError(self.reason)
