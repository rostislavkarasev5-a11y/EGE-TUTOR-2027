"""Формат обмена с контейнером runner: запрос и результат запуска в JSON (ADR-0014)."""

import base64
import json

from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxLimits, SandboxVerdict

MAX_MESSAGE_BYTES = 64 * 1024 * 1024


def request_to_json(request: RunRequest) -> bytes:
    return json.dumps(
        {
            "code": request.code,
            "stdin": request.stdin,
            "files": {
                name: base64.b64encode(content).decode("ascii")
                for name, content in request.files.items()
            },
            "limits": {
                "time_limit_seconds": request.limits.time_limit_seconds,
                "memory_limit_mb": request.limits.memory_limit_mb,
                "network_enabled": request.limits.network_enabled,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def request_from_json(raw: bytes) -> RunRequest:
    data = json.loads(raw.decode("utf-8"))
    limits = data["limits"]
    return RunRequest(
        code=str(data["code"]),
        stdin=str(data.get("stdin", "")),
        files={
            str(name): base64.b64decode(content)
            for name, content in dict(data.get("files", {})).items()
        },
        limits=SandboxLimits(
            time_limit_seconds=float(limits["time_limit_seconds"]),
            memory_limit_mb=int(limits["memory_limit_mb"]),
            network_enabled=bool(limits.get("network_enabled", False)),
        ),
    )


def result_to_json(result: RunResult) -> bytes:
    return json.dumps(
        {
            "verdict": result.verdict.value,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
        },
        ensure_ascii=False,
    ).encode("utf-8")


def result_from_json(raw: bytes) -> RunResult:
    data = json.loads(raw.decode("utf-8"))
    if "error" in data:
        raise ValueError(str(data["error"]))
    return RunResult(
        verdict=SandboxVerdict(data["verdict"]),
        stdout=str(data["stdout"]),
        stderr=str(data["stderr"]),
        exit_code=data["exit_code"],
        duration_seconds=float(data["duration_seconds"]),
    )


def error_to_json(message: str) -> bytes:
    return json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
