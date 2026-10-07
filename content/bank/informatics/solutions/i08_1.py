"""Эталонное решение: информатика №8, задача 1 (стартовый банк, ИИ)."""

from itertools import product

print(sum(1 for w in product("ЛУНА", repeat=5) if w.count("У") == 2))
