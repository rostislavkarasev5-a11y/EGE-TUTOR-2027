import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from ege_tutor.config import (
    CONFIG_DIR_ENV,
    ConfigError,
    ExamDateConfig,
    IndependenceFactors,
    load_settings,
)


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} нет в {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_exam_dates_are_tbd_by_default():
    for exam in load_settings().app.exams.values():
        assert exam.status == "TBD"
        assert exam.date is None


def test_tbd_exam_cannot_have_date():
    with pytest.raises(ValidationError):
        ExamDateConfig(status="TBD", date="2027-06-01")


def test_official_exam_requires_date_and_source():
    with pytest.raises(ValidationError):
        ExamDateConfig(status="OFFICIAL", date="2027-06-01")
    exam = ExamDateConfig(status="OFFICIAL", date="2027-06-01", source="официальный приказ")
    assert exam.date.year == 2027


def test_env_variable_selects_config_dir(config_dir, monkeypatch):
    _replace(config_dir / "app.toml", 'name = "EGE-TUTOR-2027"', 'name = "TEST"')
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config_dir))
    assert load_settings().app.app.name == "TEST"


def test_missing_config_file_is_clear_error(config_dir):
    (config_dir / "mastery.toml").unlink()
    with pytest.raises(ConfigError, match=r"mastery\.toml"):
        load_settings(config_dir)


def test_unknown_key_is_rejected(config_dir):
    _replace(config_dir / "app.toml", "enabled = false", "enabled = false\nenabeld = true")
    with pytest.raises(ConfigError, match=r"app\.toml"):
        load_settings(config_dir)


def test_missing_subject_is_rejected(config_dir):
    _replace(config_dir / "app.toml", '[exams.INFORMATICS]\nstatus = "TBD"\n', "")
    with pytest.raises(ConfigError, match="INFORMATICS"):
        load_settings(config_dir)


def test_diagnostics_cannot_enable_hints(config_dir):
    _replace(config_dir / "diagnostics.toml", "hints_allowed = false", "hints_allowed = true")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


def test_diagnostics_cannot_enable_ai(config_dir):
    _replace(config_dir / "diagnostics.toml", "ai_allowed = false", "ai_allowed = true")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


def test_mastery_factor_above_one_is_rejected(config_dir):
    _replace(config_dir / "mastery.toml", "level_0 = 1.0", "level_0 = 1.2")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_independence_factor_must_be_in_unit_interval(value):
    fields = {f"level_{i}": 0.5 for i in range(5)} | {"level_0": value}
    if 0.0 <= value <= 1.0:
        assert IndependenceFactors(**fields).level_0 == value
    else:
        with pytest.raises(ValidationError):
            IndependenceFactors(**fields)


@given(
    correct=st.floats(min_value=0.0, max_value=1.0),
    hint_level=st.integers(min_value=0, max_value=4),
    time_key=st.sampled_from(["within_norm", "up_to_double", "over_double"]),
    repeat_key=st.sampled_from(["first", "second", "third_or_later"]),
)
def test_configured_evidence_stays_in_unit_interval(correct, hint_level, time_key, repeat_key):
    """Инвариант Mastery v0: e = correctness × independence × time × repeat ∈ [0, 1]."""
    m = load_settings().mastery
    e = (
        correct
        * m.independence.for_hint_level(hint_level)
        * getattr(m.time_factor, time_key)
        * getattr(m.repeat_factor, repeat_key)
    )
    assert 0.0 <= e <= 1.0
    assert not math.isnan(e)


def test_hint_never_beats_independent_solution():
    ind = load_settings().mastery.independence
    levels = [ind.for_hint_level(i) for i in range(5)]
    assert levels == sorted(levels, reverse=True)
    assert levels[0] == 1.0
