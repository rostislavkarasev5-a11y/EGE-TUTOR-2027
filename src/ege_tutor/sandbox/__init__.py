"""Python Sandbox: реализации порта Sandbox (Phase 3, ADR-0008, ADR-0014).

На сервере — контейнер runner без сети (RunnerSocketSandbox), на компьютере — Docker
Desktop (DockerSandbox). WSL2 — запасной вариант, пока не реализован.
"""

import os
from pathlib import Path

from ege_tutor.config import SandboxConfig
from ege_tutor.core.ports.sandbox import Sandbox
from ege_tutor.sandbox.clients import DockerSandbox, RunnerSocketSandbox
from ege_tutor.sandbox.unavailable import UnavailableSandbox

RUNNER_SOCKET_ENV = "EGE_RUNNER_SOCKET"

__all__ = [
    "RUNNER_SOCKET_ENV",
    "DockerSandbox",
    "RunnerSocketSandbox",
    "UnavailableSandbox",
    "make_sandbox",
]


def make_sandbox(config: SandboxConfig) -> Sandbox:
    """Выбрать песочницу: сокет runner на сервере, иначе backend из config/app.toml."""
    socket_path = os.environ.get(RUNNER_SOCKET_ENV)
    if socket_path:
        return RunnerSocketSandbox(Path(socket_path))
    if config.backend == "docker":
        return DockerSandbox(config.docker_image)
    return UnavailableSandbox("WSL2-песочница пока не реализована, используй Docker Desktop")
