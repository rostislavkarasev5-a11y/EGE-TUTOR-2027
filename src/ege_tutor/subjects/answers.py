"""Общая проверка кратких ответов: числа, строки, наборы значений.

Правила как на бланке ЕГЭ: ответ — целое число или конечная десятичная дробь
(запятая или точка), для информатики ещё строки и несколько значений через пробел.
"""

import re
from collections.abc import Callable
from fractions import Fraction

from ege_tutor.core.domain import AnswerCheck, AnswerType, Verdict

# Запись числа, допустимая на бланке ЕГЭ: «-12», «0,4», «3.25».
EXAM_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_FRACTION_RE = re.compile(r"^(-?\d+)\s*/\s*(\d+)$")

# Значение числового выражения или None, если это не число. Математика подключает SymPy.
NumericValue = Callable[[str], Fraction | None]


def clean(text: str) -> str:
    """Убрать пробелы по краям и привести «минус» и «плюс» к обычным символам."""
    return text.strip().replace("−", "-").replace("–", "-").replace("＋", "+")


def parse_exam_number(text: str) -> Fraction | None:
    """Число в форме бланка ЕГЭ. Ведущий «+» и лишние нули допускаются."""
    value = clean(text).lstrip("+").replace(" ", "")
    if not EXAM_NUMBER_RE.match(value):
        return None
    return Fraction(value.replace(",", "."))


def parse_plain_value(text: str) -> Fraction | None:
    """Число в любой простой записи: десятичная дробь или обыкновенная «a/b»."""
    value = parse_exam_number(text)
    if value is not None:
        return value
    m = _FRACTION_RE.match(clean(text))
    if m and int(m.group(2)) != 0:
        return Fraction(int(m.group(1)), int(m.group(2)))
    return None


def _format_number(value: Fraction) -> str:
    """Как записать число на бланке (если это конечная десятичная дробь)."""
    if value.denominator == 1:
        return str(value.numerator)
    text = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def check_number(expected: str, given: str, numeric_value: NumericValue) -> AnswerCheck:
    target = Fraction(expected)
    exam_value = parse_exam_number(given)
    if exam_value is not None:
        shown = _format_number(exam_value)
        return AnswerCheck(Verdict.CORRECT if exam_value == target else Verdict.WRONG, shown)

    value = numeric_value(given)
    if value is None:
        return AnswerCheck(
            Verdict.WRONG,
            clean(given),
            "Это не похоже на число. На бланке ЕГЭ ответ — целое число или десятичная дробь.",
        )
    if value == target:
        return AnswerCheck(
            Verdict.WRONG_FORMAT,
            clean(given),
            "Значение верное, но на бланке ЕГЭ так записать нельзя: нужно "
            f"«{_format_number(target)}». На экзамене такой ответ не засчитают.",
        )
    return AnswerCheck(Verdict.WRONG, clean(given))


def _norm_text(text: str) -> str:
    return "".join(clean(text).split()).casefold()


def check_text(expected: str, given: str) -> AnswerCheck:
    normalized = _norm_text(given)
    verdict = Verdict.CORRECT if normalized == _norm_text(expected) else Verdict.WRONG
    return AnswerCheck(verdict, normalized)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s;]+", clean(text)) if t]


def _same_token(expected: str, given: str) -> bool:
    a, b = parse_exam_number(expected), parse_exam_number(given)
    if a is not None and b is not None:
        return a == b
    return expected.casefold() == given.casefold()


def check_sequence(expected: str, given: str) -> AnswerCheck:
    want, got = _tokens(expected), _tokens(given)
    normalized = " ".join(got)
    if len(want) != len(got):
        return AnswerCheck(
            Verdict.WRONG,
            normalized,
            f"Нужно {len(want)} значения через пробел, а введено {len(got)}.",
        )
    ok = all(_same_token(a, b) for a, b in zip(want, got, strict=True))
    return AnswerCheck(Verdict.CORRECT if ok else Verdict.WRONG, normalized)


def check_short_answer(
    answer_type: AnswerType, expected: str, given: str, numeric_value: NumericValue
) -> AnswerCheck:
    if answer_type == AnswerType.NUMBER:
        return check_number(expected, given, numeric_value)
    if answer_type == AnswerType.TEXT:
        return check_text(expected, given)
    if answer_type == AnswerType.SEQUENCE:
        return check_sequence(expected, given)
    raise ValueError("развёрнутый ответ проверяется по критериям (Phase 8)")
