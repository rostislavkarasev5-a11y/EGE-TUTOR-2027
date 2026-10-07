"""Защита публичного репозитория (ADR-0004): .gitignore и scripts/check_secrets.py."""

import importlib.util
import subprocess

import pytest

from tests.conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "check_secrets", REPO_ROOT / "scripts" / "check_secrets.py"
)
check_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_secrets)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "data/ege.db",
        "data/backups/2026-10-07.zip",
        "local.sqlite3",
        "data/private_content/sbornik.yaml",
        "content/private_content/task.yaml",
        "private_assets/file.xlsx",
        "config/local.toml",
        "id_rsa",
        "server.pem",
    ],
)
def test_private_paths_are_gitignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path], cwd=REPO_ROOT, check=False
    )
    assert result.returncode == 0, f"{path} не закрыт .gitignore"


@pytest.mark.parametrize("path", [".env.example", "config/app.toml", "src/ege_tutor/config.py"])
def test_public_paths_are_not_gitignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path], cwd=REPO_ROOT, check=False
    )
    assert result.returncode == 1


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.prod",
        "data/ege.db",
        "x/private_content/a.yaml",
        "private_assets/b.txt",
        "key.pem",
        "notes.sqlite",
    ],
)
def test_checker_flags_forbidden_paths(path):
    assert check_secrets.path_problem(path) is not None


@pytest.mark.parametrize("path", [".env.example", "src/ege_tutor/config.py", "docs/data.md"])
def test_checker_allows_normal_paths(path):
    assert check_secrets.path_problem(path) is None


# Фальшивые секреты собираются во время теста, чтобы сами тесты не выглядели как утечка.
@pytest.mark.parametrize(
    "text",
    [
        "key = " + "sk-ant-" + "api03-" + "x" * 40,
        "token: " + "ghp_" + "A" * 36,
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN " + "RSA PRIVATE KEY-----",
        "ANTHROPIC_API_KEY=" + "realvalue123456",
    ],
)
def test_checker_flags_secret_content(text):
    assert check_secrets.content_problems(text)


@pytest.mark.parametrize(
    "text", ["ANTHROPIC_API_KEY=", "ANTHROPIC_API_KEY=  # пусто", "обычный текст про sk-ant"]
)
def test_checker_allows_placeholders(text):
    assert check_secrets.content_problems(text) == []


def test_tracked_files_are_clean():
    files = check_secrets.tracked_files(REPO_ROOT)
    assert check_secrets.check(REPO_ROOT, files) == []
