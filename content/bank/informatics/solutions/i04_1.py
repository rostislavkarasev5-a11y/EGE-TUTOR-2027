"""Эталонное решение: информатика №4, задача 1 (стартовый банк, ИИ)."""

from itertools import product

KNOWN = {"А": "00", "Б": "011", "В": "10"}


def fano(codes):
    """Ни одно кодовое слово не является началом другого (и слова не совпадают)."""
    return all(
        not codes[j].startswith(codes[i])
        for i in range(len(codes))
        for j in range(len(codes))
        if i != j
    )


words = ["".join(p) for k in range(1, 7) for p in product("01", repeat=k)]
best = min(len(g) + len(d) for g in words for d in words if fano([*KNOWN.values(), g, d]))
print(sum(map(len, KNOWN.values())) + best)
