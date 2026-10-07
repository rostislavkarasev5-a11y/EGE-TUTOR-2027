import datetime as dt

from ege_tutor.config import load_settings
from ege_tutor.core.app import TutorApp
from ege_tutor.core.domain import Subject


def test_countdown_is_unknown_while_date_is_tbd(fixed_clock):
    tutor = TutorApp.create(clock=fixed_clock)
    countdown = tutor.exam_countdown(Subject.MATH_PROFILE)
    assert countdown.status == "TBD"
    assert countdown.date is None
    assert countdown.days_left is None


def test_countdown_uses_clock_for_official_date(config_dir, fixed_clock):
    app_toml = config_dir / "app.toml"
    text = app_toml.read_text(encoding="utf-8").replace(
        '[exams.INFORMATICS]\nstatus = "TBD"',
        '[exams.INFORMATICS]\nstatus = "OFFICIAL"\ndate = 2026-10-17\nsource = "тест"',
    )
    app_toml.write_text(text, encoding="utf-8")

    tutor = TutorApp.create(settings=load_settings(config_dir), clock=fixed_clock)
    assert tutor.exam_countdown(Subject.INFORMATICS).days_left == 10
    fixed_clock.advance(dt.timedelta(days=4))
    assert tutor.exam_countdown(Subject.INFORMATICS).days_left == 6
    assert tutor.exam_countdown(Subject.MATH_PROFILE).days_left is None


def test_info_lists_every_subject():
    info = TutorApp.create().info()
    assert {exam.subject for exam in info.exams} == set(Subject)
