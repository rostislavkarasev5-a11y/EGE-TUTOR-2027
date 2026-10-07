from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxUnavailableError


class UnavailableSandbox:
    """Sandbox ещё не реализован: любой запуск честно сообщает об этом."""

    @property
    def is_available(self) -> bool:
        return False

    def run(self, request: RunRequest) -> RunResult:
        raise SandboxUnavailableError("Python Sandbox будет реализован в Phase 3")
