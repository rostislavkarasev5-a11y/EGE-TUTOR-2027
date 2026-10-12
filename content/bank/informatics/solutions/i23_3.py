"""Эталонное решение: информатика №23, задача 3 (стартовый банк, ИИ)."""

from functools import cache

ROADS = [
    "АБ",
    "АВ",
    "АГ",
    "БВ",
    "БД",
    "ВД",
    "ВЕ",
    "ГВ",
    "ГЕ",
    "ДЖ",
    "ДЗ",
    "ЕЖ",
    "ЕИ",
    "ЖЗ",
    "ЖИ",
    "ЖК",
    "ЗК",
    "ИК",
    "ЕК",
]


@cache
def paths(start: str, finish: str) -> int:
    """Число путей из start в finish, не проходящих через город И."""
    if start == "И":
        return 0
    if start == finish:
        return 1
    return sum(paths(b, finish) for a, b in ROADS if a == start)


# Путь через Д = (путь из А в Д) × (путь из Д в К); Д стоит на пути не больше одного раза.
print(paths("А", "Д") * paths("Д", "К"))
