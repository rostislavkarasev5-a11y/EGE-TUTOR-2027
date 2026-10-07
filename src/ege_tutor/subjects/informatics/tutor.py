"""INFORMATICS TUTOR: проверка ответов КЕГЭ (числа, строки, несколько значений)."""

from ege_tutor.core.domain import AnswerCheck, AnswerType
from ege_tutor.subjects.answers import check_short_answer, parse_plain_value


class InformaticsTutor:
    def check_answer(self, answer_type: AnswerType, expected: str, given: str) -> AnswerCheck:
        return check_short_answer(answer_type, expected, given, parse_plain_value)
