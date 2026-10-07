"""Резервные копии базы (ADR-0013): согласованная копия, проверка, ротация."""

import datetime as dt
import sqlite3

import pytest
from typer.testing import CliRunner

from ege_tutor.core.app import AppError
from ege_tutor.interfaces.cli.main import app
from tests.conftest import REPO_ROOT


def test_backup_is_a_complete_database(tutor, tmp_path):
    tutor.import_tasks(REPO_ROOT / "content" / "sample" / "tasks.yaml")
    path = tutor.backup(tmp_path / "copies")
    assert path.name == "ege-20261007-090000.db"
    with sqlite3.connect(path) as conn:
        (count,) = conn.execute("SELECT count(*) FROM task").fetchone()
        (check,) = conn.execute("PRAGMA integrity_check").fetchone()
    assert count == 5
    assert check == "ok"


def test_backup_keeps_only_latest_copies(tutor, fixed_clock, tmp_path):
    folder = tmp_path / "copies"
    made = []
    for _ in range(4):
        made.append(tutor.backup(folder, keep=2))
        fixed_clock.advance(dt.timedelta(minutes=1))
    assert sorted(p.name for p in folder.iterdir()) == sorted(p.name for p in made[-2:])


def test_backup_same_second_gets_unique_name(tutor, tmp_path):
    first = tutor.backup(tmp_path)
    second = tutor.backup(tmp_path)
    assert first != second
    assert first.exists() and second.exists()


def test_backup_needs_positive_keep(tutor, tmp_path):
    with pytest.raises(AppError, match="хотя бы одну"):
        tutor.backup(tmp_path, keep=0)


def test_backup_default_folder_is_in_data_dir(tutor):
    path = tutor.backup()
    assert path.parent == tutor.settings.data_dir / "backups"


def test_cli_backup(tmp_path):
    result = CliRunner().invoke(app, ["backup", "--dir", str(tmp_path / "b"), "--keep", "3"])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "b").glob("ege-*.db"))) == 1
