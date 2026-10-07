"""ege-runner и клиенты песочницы: формат обмена, сокет, Docker, выбор реализации."""

import json
import socket
import sys
import threading
import time

import pytest
from typer.testing import CliRunner

from ege_tutor.config import SandboxConfig
from ege_tutor.core.ports.sandbox import (
    RunRequest,
    RunResult,
    SandboxLimits,
    SandboxUnavailableError,
    SandboxVerdict,
)
from ege_tutor.sandbox import (
    RUNNER_SOCKET_ENV,
    DockerSandbox,
    RunnerSocketSandbox,
    UnavailableSandbox,
    make_sandbox,
    protocol,
    runner,
)

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="движок песочницы работает только на Linux"
)
REQUEST = RunRequest(
    code="print(input())",
    stdin="7",
    files={"a.txt": b"\x00\x01"},
    limits=SandboxLimits(2, 128),
)


def test_protocol_roundtrip():
    assert protocol.request_from_json(protocol.request_to_json(REQUEST)) == REQUEST
    result = RunResult(SandboxVerdict.OK, "вывод", "", 0, 0.5)
    assert protocol.result_from_json(protocol.result_to_json(result)) == result
    with pytest.raises(ValueError, match="сломалось"):
        protocol.result_from_json(protocol.error_to_json("сломалось"))


def test_runner_caps_limits_and_disables_network():
    greedy = RunRequest(code="", limits=SandboxLimits(3600, 100_000, network_enabled=True))
    capped = runner._capped(greedy)
    assert capped.limits.time_limit_seconds == runner.MAX_TIME_SECONDS
    assert capped.limits.memory_limit_mb == runner.MAX_MEMORY_MB
    assert capped.limits.network_enabled is False


def test_runner_answers_errors_instead_of_crashing():
    assert runner.handle(runner.PING) == runner.PONG
    assert "error" in json.loads(runner.handle(b"not json"))


@linux_only
def test_runner_once():
    result = CliRunner().invoke(runner.app, ["once"], input=protocol.request_to_json(REQUEST))
    assert result.exit_code == 0, result.output
    assert protocol.result_from_json(result.stdout_bytes).stdout == "7\n"


@pytest.fixture
def served(tmp_path):
    """Настоящий runner на Unix-сокете в отдельном потоке."""
    if not hasattr(socket, "AF_UNIX") or not sys.platform.startswith("linux"):
        pytest.skip("Unix-сокеты песочницы — только Linux")
    path = tmp_path / "runner.sock"
    thread = threading.Thread(
        target=lambda: CliRunner().invoke(runner.app, ["serve", "--socket", str(path)]),
        daemon=True,
    )
    thread.start()
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.05)
    return path


@linux_only
def test_socket_sandbox_runs_programs(served):
    sandbox = RunnerSocketSandbox(served)
    assert sandbox.is_available
    result = sandbox.run(REQUEST)
    assert result.verdict == SandboxVerdict.OK
    assert result.stdout == "7\n"
    ping = CliRunner().invoke(runner.app, ["ping", "--socket", str(served)])
    assert ping.exit_code == 0, ping.output


def test_socket_sandbox_without_runner(tmp_path):
    sandbox = RunnerSocketSandbox(tmp_path / "nothing.sock")
    assert sandbox.is_available is False
    with pytest.raises(SandboxUnavailableError):
        sandbox.run(REQUEST)


def test_docker_sandbox_isolation_flags():
    command = DockerSandbox("ege-tutor:test").command(REQUEST)
    joined = " ".join(command)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit",
        "--rm",
    ):
        assert flag in joined
    assert command[-3:] == ["ege-tutor:test", "ege-runner", "once"]


def test_docker_sandbox_without_docker(monkeypatch):
    monkeypatch.setattr("ege_tutor.sandbox.clients.shutil.which", lambda _name: None)
    sandbox = DockerSandbox()
    assert sandbox.is_available is False
    with pytest.raises(SandboxUnavailableError, match="Docker Desktop"):
        sandbox.run(REQUEST)


def test_make_sandbox_choice(monkeypatch, tmp_path):
    config = SandboxConfig(
        backend="docker", time_limit_seconds=10, memory_limit_mb=256, network_enabled=False
    )
    monkeypatch.delenv(RUNNER_SOCKET_ENV, raising=False)
    assert isinstance(make_sandbox(config), DockerSandbox)
    wsl = make_sandbox(config.model_copy(update={"backend": "wsl2"}))
    assert isinstance(wsl, UnavailableSandbox)
    monkeypatch.setenv(RUNNER_SOCKET_ENV, str(tmp_path / "r.sock"))
    chosen = make_sandbox(config)
    assert isinstance(chosen, RunnerSocketSandbox)
    assert chosen.socket_path == tmp_path / "r.sock"
