"""Скрипты Windows: окончания строк и обязательные части."""

import pytest

from tests.conftest import REPO_ROOT

SCRIPTS = ["install.bat", "update.bat", "ege-console.bat"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_bat_uses_crlf_and_utf8_console(name):
    raw = (REPO_ROOT / name).read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n"), "в .bat нужны окончания строк CRLF"
    text = raw.decode("utf-8")
    assert "chcp 65001" in text


@pytest.mark.parametrize("name", ["install.bat", "update.bat"])
def test_bat_can_run_without_pause_in_ci(name):
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    assert "EGE_NONINTERACTIVE" in text
    assert "uv sync --locked" in text
    assert "uv run ege init" in text
