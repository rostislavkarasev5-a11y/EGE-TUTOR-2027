"""Движок Linux-native: «злые» программы останавливаются (архитектура, раздел 9).

Движок работает только на Linux (на Windows — внутри контейнера Docker), поэтому на
других системах эти тесты не запускаются. Сеть отключает контейнер (--network none):
её проверяет selftest в CI внутри контейнера.
"""

import os
import sys

import pytest

from ege_tutor.core.ports.sandbox import (
    RunRequest,
    SandboxLimits,
    SandboxUnavailableError,
    SandboxVerdict,
)
from ege_tutor.sandbox.engine import run_local

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="движок песочницы работает только на Linux"
)
LIMITS = SandboxLimits(time_limit_seconds=2, memory_limit_mb=256)


def run(code: str, **kwargs) -> object:
    return run_local(RunRequest(code=code, limits=LIMITS, **kwargs))


@linux_only
def test_normal_program_with_stdin_and_files():
    code = "import sys\nprint(sys.stdin.read().upper())\nprint(open('data/a.txt').read())"
    result = run(code, stdin="привет", files={"data/a.txt": b"42"})
    assert result.verdict == SandboxVerdict.OK
    assert result.stdout.split() == ["ПРИВЕТ", "42"]
    assert result.exit_code == 0


@linux_only
@pytest.mark.parametrize(
    "code", ["while True:\n    pass", "import time\ntime.sleep(30)"], ids=["cpu", "sleep"]
)
def test_endless_programs_are_stopped(code):
    result = run(code)
    assert result.verdict == SandboxVerdict.TIME_LIMIT
    assert result.duration_seconds < 6


@linux_only
def test_memory_is_limited():
    result = run("x = bytearray(10 * 1024**3)")
    assert result.verdict == SandboxVerdict.MEMORY_LIMIT


@linux_only
def test_fork_bomb_is_stopped():
    result = run("import os\nwhile True:\n    os.fork()")
    assert result.verdict in {SandboxVerdict.RUNTIME_ERROR, SandboxVerdict.TIME_LIMIT}


@linux_only
def test_child_processes_do_not_survive(tmp_path):
    marker = tmp_path / "alive"
    code = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    time.sleep(3)\n"
        f"    open({str(marker)!r}, 'w').write('x')\n"
        "print('done')"
    )
    assert run(code).verdict == SandboxVerdict.OK
    import time

    time.sleep(3.5)
    assert not marker.exists()


@linux_only
def test_huge_output_is_stopped():
    result = run("import sys\nwhile True:\n    sys.stdout.write('x' * 65536)")
    assert result.verdict == SandboxVerdict.RUNTIME_ERROR
    assert len(result.stdout) < 1_100_000


@linux_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root может писать в /etc")
def test_system_files_are_protected():
    result = run("open('/etc/ege-evil', 'w').write('x')")
    assert result.verdict == SandboxVerdict.RUNTIME_ERROR


@linux_only
def test_syntax_and_runtime_errors():
    syntax = run("print(")
    assert syntax.verdict == SandboxVerdict.SYNTAX_ERROR
    assert "строка 1" in syntax.stderr
    crash = run("print(1/0)")
    assert crash.verdict == SandboxVerdict.RUNTIME_ERROR
    assert "ZeroDivisionError" in crash.stderr
    assert run("\0").verdict == SandboxVerdict.SYNTAX_ERROR


@linux_only
def test_environment_is_clean(monkeypatch):
    monkeypatch.setenv("EGE_WEB_SECRET_KEY", "-".join(["не", "должно", "утечь"]))
    result = run("import os\nprint(sorted(os.environ))")
    assert "EGE_WEB_SECRET_KEY" not in result.stdout


@linux_only
def test_unsafe_file_names_are_rejected():
    with pytest.raises(ValueError, match="недопустимое имя"):
        run("print(1)", files={"../evil.txt": b"x"})


@linux_only
def test_too_long_program():
    assert run("#" * 100_001).verdict == SandboxVerdict.RUNTIME_ERROR


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="проверка для Windows и macOS")
def test_engine_refuses_outside_linux():
    with pytest.raises(SandboxUnavailableError, match="только на Linux"):
        run("print(1)")
