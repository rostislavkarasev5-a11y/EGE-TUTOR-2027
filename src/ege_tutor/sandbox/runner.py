"""Команда ege-runner: работает внутри контейнера runner без сети (ADR-0014).

- `ege-runner serve --socket PATH` — ждать программы через Unix-сокет (сервер);
- `ege-runner once` — один запуск: запрос JSON со stdin, результат JSON в stdout (Windows,
  `docker run --rm -i --network none ...`);
- `ege-runner selftest` — прогнать «злые» программы и убедиться, что всё остановлено;
- `ege-runner ping --socket PATH` — проверка, что runner отвечает (healthcheck).
"""

import os
import socket
import socketserver
import sys
import threading
from pathlib import Path
from typing import Annotated

import typer

from ege_tutor.core.ports.sandbox import RunRequest, SandboxLimits, SandboxVerdict
from ege_tutor.sandbox import protocol
from ege_tutor.sandbox.engine import run_local

PING = b'{"ping": true}'
PONG = b'{"pong": true}'
MAX_TIME_SECONDS = 60.0
MAX_MEMORY_MB = 1024
# Программы запускаются строго по одной: лимиты контейнера рассчитаны на один запуск.
# Проверка связи (ping) при этом отвечает сразу, не дожидаясь очереди.
_RUN_LOCK = threading.Lock()

app = typer.Typer(help="Запуск программ на Python в песочнице.", add_completion=False)


def _read_all(conn: socket.socket) -> bytes:
    chunks, size = [], 0
    while chunk := conn.recv(1 << 16):
        size += len(chunk)
        if size > protocol.MAX_MESSAGE_BYTES:
            raise ValueError("слишком большой запрос")
        chunks.append(chunk)
    return b"".join(chunks)


def _capped(request: RunRequest) -> RunRequest:
    """Лимиты не больше потолка runner: запрос не может выдать себе час и 10 ГБ."""
    limits = request.limits
    return RunRequest(
        code=request.code,
        stdin=request.stdin,
        files=request.files,
        limits=SandboxLimits(
            time_limit_seconds=min(limits.time_limit_seconds, MAX_TIME_SECONDS),
            memory_limit_mb=min(limits.memory_limit_mb, MAX_MEMORY_MB),
            network_enabled=False,
        ),
    )


def handle(raw: bytes) -> bytes:
    """Обработать один запрос и вернуть ответ (без исключений наружу)."""
    if raw.strip() == PING:
        return PONG
    try:
        request = _capped(protocol.request_from_json(raw))
        with _RUN_LOCK:
            result = run_local(request)
        return protocol.result_to_json(result)
    except Exception as e:  # ответ об ошибке лучше, чем оборванное соединение
        return protocol.error_to_json(f"{type(e).__name__}: {e}")


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn: socket.socket = self.request
        try:
            raw = _read_all(conn)
        except ValueError as e:
            conn.sendall(protocol.error_to_json(str(e)))
            return
        conn.sendall(handle(raw))


@app.command()
def serve(
    socket_path: Annotated[Path, typer.Option("--socket", help="Путь к Unix-сокету.")],
) -> None:
    """Ждать программы через Unix-сокет. Запуски идут по очереди."""

    class Server(socketserver.ThreadingUnixStreamServer):  # есть только на Linux/macOS
        daemon_threads = True

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    os.umask(0o007)
    with Server(str(socket_path), _Handler) as server:
        typer.echo(f"runner слушает {socket_path}")
        server.serve_forever()


@app.command()
def ping(
    socket_path: Annotated[Path, typer.Option("--socket", help="Путь к Unix-сокету.")],
) -> None:
    """Проверить, что runner отвечает (для healthcheck контейнера)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(3)
            conn.connect(str(socket_path))
            conn.sendall(PING)
            conn.shutdown(socket.SHUT_WR)
            answer = _read_all(conn)
    except (OSError, ValueError) as e:
        typer.echo(f"runner не отвечает: {e}", err=True)
        raise typer.Exit(code=1) from e
    if answer != PONG:
        raise typer.Exit(code=1)
    typer.echo("ok")


@app.command()
def once() -> None:
    """Один запуск: запрос JSON на входе, результат JSON на выходе."""
    raw = sys.stdin.buffer.read(protocol.MAX_MESSAGE_BYTES + 1)
    if len(raw) > protocol.MAX_MESSAGE_BYTES:
        sys.stdout.buffer.write(protocol.error_to_json("слишком большой запрос"))
        return
    sys.stdout.buffer.write(handle(raw))


SELFTEST: list[tuple[str, str, set[SandboxVerdict]]] = [
    ("обычная программа", "print(sum(range(10)))", {SandboxVerdict.OK}),
    ("бесконечный цикл", "while True:\n    pass", {SandboxVerdict.TIME_LIMIT}),
    ("10 ГБ памяти", "x = bytearray(10 * 1024**3)", {SandboxVerdict.MEMORY_LIMIT}),
    (
        "форк-бомба",
        "import os\nwhile True:\n    os.fork()",
        {SandboxVerdict.RUNTIME_ERROR, SandboxVerdict.TIME_LIMIT},
    ),
    (
        "сеть",
        "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)",
        {SandboxVerdict.RUNTIME_ERROR},
    ),
    ("запись в /etc", "open('/etc/ege-evil', 'w').write('x')", {SandboxVerdict.RUNTIME_ERROR}),
    (
        "запись в домашнюю папку системы",
        "open('/home/ege-evil', 'w').write('x')",
        {SandboxVerdict.RUNTIME_ERROR},
    ),
    (
        "огромный вывод",
        "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)",
        {SandboxVerdict.RUNTIME_ERROR},
    ),
]


@app.command()
def selftest() -> None:
    """Проверить, что «злые» программы останавливаются. Код выхода 1 — что-то не так."""
    limits = SandboxLimits(time_limit_seconds=3, memory_limit_mb=256)
    failed = 0
    for title, code, expected in SELFTEST:
        result = run_local(RunRequest(code=code, limits=limits))
        ok = result.verdict in expected
        failed += not ok
        mark = "ok  " if ok else "FAIL"
        typer.echo(f"{mark} {title}: {result.verdict} ({result.duration_seconds} с)")
    if failed:
        raise typer.Exit(code=1)


def run() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    app()
