"""MATH TUTOR: проверка кратких ответов профильной математики."""

from ege_tutor.core.domain import AnswerCheck, AnswerType
from ege_tutor.subjects.answers import check_short_answer, parse_plain_value
from ege_tutor.subjects.math.expressions import numeric_value


def _value(text: str):
    return parse_plain_value(text) or numeric_value(text)


class MathTutor:
    def check_answer(self, answer_type: AnswerType, expected: str, given: str) -> AnswerCheck:
        return check_short_answer(answer_type, expected, given, _value)
