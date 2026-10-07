import datetime as dt
import shutil
from pathlib import Path

import pytest

from ege_tutor.config import DATA_DIR_ENV, default_config_dir
from ege_tutor.core.clock import FixedClock

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Каждый тест работает со своей временной базой, а не с data/ пользователя."""
    target = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(target))
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
