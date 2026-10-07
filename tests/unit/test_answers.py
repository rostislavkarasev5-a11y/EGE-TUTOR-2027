"""Проверка кратких ответов (subjects/): формат бланка ЕГЭ, информатика, SymPy."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from ege_tutor.core.domain import AnswerType, Subject, Verdict
from ege_tutor.subjects import tutor_for
from ege_tutor.subjects.math.expressions import numeric_value

math = tutor_for(Subject.MATH_PROFILE)
inf = tutor_for(Subject.INFORMATICS)


@pytest.mark.parametrize(
    ("expected", "given", "verdict"),
    [
        ("0.4", "0,4", Verdict.CORRECT),
        ("0.4", "0.40", Verdict.CORRECT),
        ("-0.5", "−0,5", Verdict.CORRECT),
        ("6", "+6", Verdict.CORRECT),
        ("6", " 6 ", Verdict.CORRECT),
        ("6", "7", Verdict.WRONG),
        ("0.4", "2/5", Verdict.WRONG_FORMAT),
        ("4", "√16", Verdict.WRONG_FORMAT),
        ("4", "2^2", Verdict.WRONG_FORMAT),
        ("3", "log(8, 2)", Verdict.WRONG_FORMAT),
        ("0.4", "abc", Verdict.WRONG),
        ("0.4", "1/3", Verdict.WRONG),
    ],
)
def test_math_numbers(expected, given, verdict):
    assert math.check_answer(AnswerType.NUMBER, expected, given).verdict == verdict


def test_wrong_format_explains_how_to_write():
    check = math.check_answer(AnswerType.NUMBER, "0.4", "2/5")
    assert not check.correct
    assert "0,4" in check.explanation


def test_informatics_has_no_sympy_but_accepts_fractions_as_value():
    assert inf.check_answer(AnswerType.NUMBER, "4", "√16").verdict == Verdict.WRONG
    assert inf.check_answer(AnswerType.NUMBER, "0.5", "1/2").verdict == Verdict.WRONG_FORMAT


@pytest.mark.parametrize(
    ("expected", "given", "verdict"),
    [
        ("12 3456", "12 3456", Verdict.CORRECT),
        ("12 3456", "12   3456", Verdict.CORRECT),
        ("12 3456", "12;3456", Verdict.CORRECT),
        ("12 3456", "3456 12", Verdict.WRONG),
        ("12 3456", "12", Verdict.WRONG),
    ],
)
def test_sequences(expected, given, verdict):
    assert inf.check_answer(AnswerType.SEQUENCE, expected, given).verdict == verdict


def test_text_ignores_case_and_spaces():
    assert inf.check_answer(AnswerType.TEXT, "xzyw", "XZ YW").correct
    assert not inf.check_answer(AnswerType.TEXT, "xzyw", "xywz").correct


def test_extended_is_not_checked_here():
    with pytest.raises(ValueError, match="Phase 8"):
        math.check_answer(AnswerType.EXTENDED, "1", "1")


@pytest.mark.parametrize(
    "text",
    ["__import__('os')", "exit()", "a.b", "9^9^9", "x" * 50, "open('f')", "lambda: 1", "√", ""],
)
def test_expression_parser_rejects_anything_but_math(text):
    assert numeric_value(text) is None


@given(st.decimals(min_value=-(10**6), max_value=10**6, places=3, allow_nan=False))
def test_any_exam_style_number_equal_to_answer_is_correct(value):
    expected = format(value.normalize(), "f")
    for given_text in (format(value, "f"), format(value, "f").replace(".", ",")):
        assert math.check_answer(AnswerType.NUMBER, expected, given_text).correct


@given(st.text(max_size=40))
@example(")")  # SymPy падал с IndexError на одной скобке
@example("(")  # и с TokenError на незакрытой
def test_checker_never_crashes(text):
    for tutor in (math, inf):
        for answer_type, expected in (
            (AnswerType.NUMBER, "1.5"),
            (AnswerType.TEXT, "abc"),
            (AnswerType.SEQUENCE, "1 2"),
        ):
            check = tutor.check_answer(answer_type, expected, text)
            assert check.verdict in set(Verdict)
