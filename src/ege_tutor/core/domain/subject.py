from enum import StrEnum


class Subject(StrEnum):
    """Предметы ЕГЭ, которые поддерживает система."""

    MATH_PROFILE = "MATH_PROFILE"
    INFORMATICS = "INFORMATICS"
