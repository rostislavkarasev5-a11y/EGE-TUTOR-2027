"""Движок Linux-native: запуск одной программы на Python с ограничениями (архитектура, раздел 9).

Работает только на Linux. На сервере вызывается внутри контейнера runner без сети
(ADR-0014), на Windows — внутри того же образа через Docker Desktop (ADR-0008).
Сеть здесь не отключается: это делает окружение (`network_mode: none`, `--network none`).

Ограничения каждого запуска:
- отдельная временная папка, файлы задачи копируются в неё;
- `python -I` (без пользовательских путей и переменных), чистое окружение;
- RLIMIT_CPU (процессорное время), RLIMIT_AS (память), RLIMIT_NPROC (процессы),
  RLIMIT_FSIZE (размер файлов, в том числе вывода), без core-файлов;
- таймер по реальному времени: по его истечении убивается вся группа процессов.
"""

import contextlib
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from ege_tutor.core.ports.sandbox import (
    RunRequest,
    RunResult,
    SandboxUnavailableError,
    SandboxVerdict,
)

MAX_CODE_BYTES = 100_000
MAX_OUTPUT_BYTES = 1_000_000
FILE_SIZE_LIMIT_BYTES = 16 * 1024 * 1024
PROCESS_LIMIT = 64
_MB = 1024 * 1024


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"недопустимое имя файла: {name}")
    return path


def _read_limited(path: Path) -> str:
    with path.open("rb") as f:
        data = f.read(MAX_OUTPUT_BYTES + 1)
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        text += "\n… (вывод обрезан)"
    return text


def _limits(cpu_seconds: int, memory_bytes: int):
    """Функция для preexec_fn: выставить лимиты уже в дочернем процессе."""

    def apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (PROCESS_LIMIT, PROCESS_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.umask(0o077)

    return apply


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def run_local(
    request: RunRequest,
    *,
    python: str = sys.executable,
    temp_root: Path | None = None,
) -> RunResult:
    """Запустить программу из request с его лимитами и вернуть результат."""
    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise SandboxUnavailableError("движок Linux-native работает только на Linux")
    if len(request.code.encode("utf-8")) > MAX_CODE_BYTES:
        return RunResult(SandboxVerdict.RUNTIME_ERROR, "", "Программа длиннее 100 КБ.", None, 0.0)
    try:
        compile(request.code, "main.py", "exec")
    except SyntaxError as e:
        where = f" (строка {e.lineno})" if e.lineno else ""
        message = f"{type(e).__name__}: {e.msg}{where}"
        return RunResult(SandboxVerdict.SYNTAX_ERROR, "", message, None, 0.0)
    except ValueError as e:  # например, нулевой байт в тексте программы
        return RunResult(SandboxVerdict.SYNTAX_ERROR, "", f"ValueError: {e}", None, 0.0)

    limits = request.limits
    wall_seconds = limits.time_limit_seconds
    cpu_seconds = max(1, math.ceil(wall_seconds))
    memory_bytes = limits.memory_limit_mb * _MB

    with tempfile.TemporaryDirectory(prefix="ege-run-", dir=temp_root) as tmp:
        root = Path(tmp)
        work = root / "work"
        work.mkdir()
        for name, content in request.files.items():
            target = work.joinpath(*_safe_name(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        program = root / "main.py"
        program.write_text(request.code, encoding="utf-8")
        out_path, err_path = root / "stdout", root / "stderr"
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(work),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        timed_out = False
        started = time.monotonic()
        with out_path.open("wb") as out, err_path.open("wb") as err:
            proc = subprocess.Popen(
                [python, "-I", "-X", "utf8", str(program)],
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                cwd=work,
                env=env,
                start_new_session=True,  # своя группа процессов: убиваем всех потомков разом
                preexec_fn=_limits(
                    cpu_seconds, memory_bytes
                ),  # лимиты ставятся в дочернем процессе
                close_fds=True,
            )
            try:
                proc.communicate(request.stdin.encode("utf-8"), timeout=wall_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc.pid)
                proc.wait()
            except BrokenPipeError:
                proc.wait()
            finally:
                _kill_group(proc.pid)  # потомки, оставшиеся после выхода программы
        duration = time.monotonic() - started
        stdout = _read_limited(out_path)
        stderr = _read_limited(err_path)

    code = proc.returncode
    if timed_out or code in (-signal.SIGXCPU, -signal.SIGKILL):
        verdict = SandboxVerdict.TIME_LIMIT
        stderr = (stderr + "\nПревышено время работы.").strip()
    elif "MemoryError" in stderr:
        verdict = SandboxVerdict.MEMORY_LIMIT
    elif code == -signal.SIGXFSZ:
        verdict = SandboxVerdict.RUNTIME_ERROR
        stderr = (stderr + "\nСлишком большой вывод или файл (больше 16 МБ).").strip()
    elif code != 0:
        verdict = SandboxVerdict.RUNTIME_ERROR
    else:
        verdict = SandboxVerdict.OK
    return RunResult(verdict, stdout, stderr, code, round(duration, 3))
