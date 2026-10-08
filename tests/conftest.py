import datetime as dt
import shutil
from pathlib import Path

import pytest

from ege_tutor.config import (
    AI_BUDGET_ENV,
    AI_MODEL_ENV,
    AI_PROVIDER_ENV,
    DATA_DIR_ENV,
    default_config_dir,
)
from ege_tutor.core.clock import FixedClock

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_ENV_NAMES = (
    AI_PROVIDER_ENV,
    AI_MODEL_ENV,
    AI_BUDGET_ENV,
    "EGE_YANDEX_API_KEY",
    "EGE_YANDEX_FOLDER_ID",
)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Каждый тест работает со своей временной базой, а не с data/ пользователя."""
    target = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(target))
    # Настройки ИИ с компьютера разработчика не должны влиять на тесты (ADR-0017).
    for name in AI_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return target


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Копия config/ репозитория, которую тест может менять."""
    target = tmp_path / "config"
    shutil.copytree(default_config_dir(), target)
    return target


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(dt.datetime(2026, 10, 7, 9, 0, tzinfo=dt.UTC))


@pytest.fixture
def tutor(fixed_clock: FixedClock):
    """Приложение с пустой временной базой и фиксированным временем."""
    from ege_tutor.core.app import TutorApp

    app = TutorApp.create(clock=fixed_clock)
    yield app
    app.close()


@pytest.fixture
def write_file(tmp_path: Path):
    """Записать файл во временную папку теста и вернуть путь."""

    def _write(name: str, content: str | bytes) -> Path:
        path = tmp_path / "input" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    return _write
