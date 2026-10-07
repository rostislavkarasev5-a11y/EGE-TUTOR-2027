"""Реализации порта Sandbox, которые передают программу в контейнер runner (ADR-0014).

- RunnerSocketSandbox — на сервере: контейнер runner уже запущен, связь через Unix-сокет;
- DockerSandbox — на компьютере (Windows, Docker Desktop, ADR-0008): на каждый запуск
  новый контейнер `docker run --rm --network none ...` из того же образа.
"""

import shutil
import socket
import subprocess
from pathlib import Path

from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxUnavailableError
from ege_tutor.sandbox import protocol

PING = b'{"ping": true}'
DEFAULT_IMAGE = "ege-tutor:latest"
_DOCKER_OVERHEAD_SECONDS = 30  # запуск контейнера сам по себе занимает время


class RunnerSocketSandbox:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path

    def _exchange(self, payload: bytes, timeout: float) -> bytes:
        if not hasattr(socket, "AF_UNIX"):
            raise SandboxUnavailableError("Unix-сокеты недоступны в этой системе")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            try:
                conn.connect(str(self.socket_path))
                conn.sendall(payload)
                conn.shutdown(socket.SHUT_WR)
                chunks = []
                while chunk := conn.recv(1 << 16):
                    chunks.append(chunk)
            except OSError as e:
                raise SandboxUnavailableError(f"песочница не отвечает: {e}") from e
        return b"".join(chunks)

    @property
    def is_available(self) -> bool:
        try:
            return b"pong" in self._exchange(PING, timeout=2)
        except SandboxUnavailableError:
            return False

    def run(self, request: RunRequest) -> RunResult:
        timeout = request.limits.time_limit_seconds + 15
        raw = self._exchange(protocol.request_to_json(request), timeout)
        try:
            return protocol.result_from_json(raw)
        except ValueError as e:
            raise SandboxUnavailableError(f"ошибка песочницы: {e}") from e


class DockerSandbox:
    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        self.image = image

    def _docker(self) -> str | None:
        return shutil.which("docker")

    @property
    def is_available(self) -> bool:
        docker = self._docker()
        if docker is None:
            return False
        try:
            found = subprocess.run(
                [docker, "image", "inspect", self.image],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return found.returncode == 0

    def command(self, request: RunRequest) -> list[str]:
        memory = request.limits.memory_limit_mb + 256  # запас на сам Python и runner
        return [
            self._docker() or "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=64m",
            "--memory",
            f"{memory}m",
            "--memory-swap",
            f"{memory}m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            self.image,
            "ege-runner",
            "once",
        ]

    def run(self, request: RunRequest) -> RunResult:
        if self._docker() is None:
            raise SandboxUnavailableError(
                "не найден Docker. Установи Docker Desktop (инструкция в README)"
            )
        try:
            done = subprocess.run(
                self.command(request),
                input=protocol.request_to_json(request),
                capture_output=True,
                timeout=request.limits.time_limit_seconds + _DOCKER_OVERHEAD_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxUnavailableError("Docker не ответил вовремя") from e
        if done.returncode != 0:
            message = done.stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise SandboxUnavailableError(f"Docker не смог запустить песочницу: {message}")
        try:
            return protocol.result_from_json(done.stdout)
        except ValueError as e:
            raise SandboxUnavailableError(f"ошибка песочницы: {e}") from e
