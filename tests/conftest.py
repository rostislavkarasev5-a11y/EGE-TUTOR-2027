import datetime as dt
import shutil
from pathlib import Path

import pytest

from ege_tutor.config import default_config_dir
from ege_tutor.core.clock import FixedClock

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Копия config/ репозитория, которую тест может менять."""
    target = tmp_path / "config"
    shutil.copytree(default_config_dir(), target)
    return target


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(dt.datetime(2026, 10, 7, 9, 0, tzinfo=dt.UTC))
