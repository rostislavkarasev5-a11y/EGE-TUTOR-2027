from enum import StrEnum

# Короткие имена, которые удобно набирать в командной строке и в файлах импорта.
SUBJECT_ALIASES = {
    "math": "MATH_PROFILE",
    "математика": "MATH_PROFILE",
    "informatics": "INFORMATICS",
    "inf": "INFORMATICS",
    "информатика": "INFORMATICS",
}


class Subject(StrEnum):
    """Предметы ЕГЭ, которые поддерживает система."""

    MATH_PROFILE = "MATH_PROFILE"
    INFORMATICS = "INFORMATICS"

    @classmethod
    def parse(cls, text: str) -> "Subject":
        """Распознать предмет по коду или короткому имени. ValueError, если не удалось."""
        value = text.strip()
        return cls(SUBJECT_ALIASES.get(value.lower(), value.upper()))
