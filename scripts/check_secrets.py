"""Проверка публичного репозитория на случайную публикацию секретов и личных данных (ADR-0004).

Проверяет файлы, которые отслеживает git (или переданные аргументами):
1. запрещённые пути: .env, базы данных, data/, private_content/, private_assets/, ключи;
2. содержимое: строки, похожие на API-ключи, токены и приватные ключи.

Запуск: uv run python scripts/check_secrets.py
Код выхода 0 — чисто, 1 — найдены проблемы.
"""

import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

FORBIDDEN_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.db",
    "*.db-journal",
    "*.sqlite",
    "*.sqlite3",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "secrets.toml",
    "*.secret",
)
ALLOWED_PATHS = {".env.example"}
FORBIDDEN_DIRS = {"data", "private_content", "private_assets", "backups"}

SECRET_PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "OpenAI-style API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Filled API key variable": re.compile(
        r"^\s*[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"]?[^\s'\"#]{8,}", re.MULTILINE
    ),
}

MAX_SCAN_BYTES = 2_000_000


def path_problem(path: str) -> str | None:
    """Причина, по которой путь нельзя публиковать, или None."""
    p = PurePosixPath(path)
    if path in ALLOWED_PATHS:
        return None
    if FORBIDDEN_DIRS.intersection(p.parts[:-1]):
        return "личные данные или закрытый контент"
    if any(fnmatch(p.name, pattern) for pattern in FORBIDDEN_PATH_PATTERNS):
        return "файл секретов или локальная база"
    return None


def content_problems(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return [f for f in out.decode("utf-8").split("\0") if f]


def check(root: Path, files: list[str]) -> list[str]:
    problems = []
    for rel in files:
        reason = path_problem(rel)
        if reason:
            problems.append(f"{rel}: {reason}")
            continue
        path = root / rel
        if not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # бинарный файл
        problems.extend(f"{rel}: похоже на секрет ({name})" for name in content_problems(text))
    return problems


def main(argv: list[str]) -> int:
    root = Path.cwd()
    files = argv or tracked_files(root)
    problems = check(root, files)
    if problems:
        print("Найдены файлы, которые нельзя публиковать в публичном репозитории:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Проверка секретов: чисто ({len(files)} файлов).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
