"""Значение числового выражения через SymPy (вспомогательно, ADR-0003).

Нужен только чтобы понять, что «2/5» или «√16» по значению совпадает с эталоном,
и подсказать, как записать ответ на бланке. Баллы SymPy не ставит.
Ввод ограничен белым списком символов и имён: произвольный код не выполняется.
"""

import re
from fractions import Fraction
from tokenize import TokenError

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

MAX_LENGTH = 40
_ALLOWED_CHARS = re.compile(r"^[0-9a-z+\-*/^().,\s√π]*$")
_NAMES = {"sqrt": "sqrt", "pi": "pi", "log": "log", "ln": "log", "sin": "sin", "cos": "cos"}
_NAMES |= {"tan": "tan", "tg": "tan", "cot": "cot", "ctg": "cot"}
_TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)


def _prepare(text: str) -> str | None:
    value = text.strip().lower().replace("−", "-").replace("π", " pi ")
    if not value or len(value) > MAX_LENGTH or not _ALLOWED_CHARS.match(value):
        return None
    for name in re.findall(r"[a-z]+", value):
        if name not in _NAMES:
            return None
    if value.count("^") + value.count("**") > 1:  # защита от огромных степеней вроде 9^9^9
        return None
    value = re.sub(r"[a-z]+", lambda m: _NAMES[m.group(0)], value)
    value = re.sub(r"√\s*(\d+(?:[.,]\d+)?|\([^()]*\))", r"sqrt(\1)", value)
    if "√" in value:
        return None
    if "log" not in value:  # в log(8, 2) запятая разделяет аргументы
        value = re.sub(r"(\d),(\d)", r"\1.\2", value)
    return value


def numeric_value(text: str) -> Fraction | None:
    """Точное рациональное значение выражения или None (не число или иррациональное)."""
    prepared = _prepare(text)
    if prepared is None:
        return None
    try:
        expr = sympy.nsimplify(parse_expr(prepared, transformations=_TRANSFORMS))
    except (
        SyntaxError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        AttributeError,
        IndexError,
        TokenError,  # незакрытая скобка: «(»
    ):
        return None
    if not expr.is_number or not expr.is_rational:
        return None
    rational = sympy.Rational(expr)
    return Fraction(int(rational.p), int(rational.q))
