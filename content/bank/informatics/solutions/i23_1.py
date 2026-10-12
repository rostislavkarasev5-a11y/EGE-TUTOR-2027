"""Эталонное решение: информатика №23, задача 1 (стартовый банк, ИИ)."""

from functools import cache

ROADS = ["АБ", "АВ", "АГ", "БД", "ВД", "ВЕ", "ГЕ", "ДЖ", "ЕЖ", "ДК", "ЖК", "ЕК"]


@cache
def paths(town: str) -> int:
    """Число путей из town в К по односторонним дорогам."""
    if town == "К":
        return 1
    return sum(paths(b) for a, b in ROADS if a == town)


print(paths("А"))
