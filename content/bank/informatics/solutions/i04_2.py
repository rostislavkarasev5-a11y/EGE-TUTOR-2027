"""Эталонное решение: информатика №4, задача 2 (стартовый банк, ИИ)."""

from itertools import product

WORD = "КАРАКУРТ"
KNOWN = {"Р": "01", "У": "110"}
FREE = ["К", "А", "Т"]


def fano(codes):
    """Ни одно кодовое слово не является началом другого (и слова не совпадают)."""
    return all(
        not codes[j].startswith(codes[i])
        for i in range(len(codes))
        for j in range(len(codes))
        if i != j
    )


words = ["".join(p) for k in range(1, 6) for p in product("01", repeat=k)]
best = None
for choice in product(words, repeat=len(FREE)):
    if fano([*KNOWN.values(), *choice]):
        codes = KNOWN | dict(zip(FREE, choice, strict=True))
        length = sum(len(codes[ch]) for ch in WORD)
        best = length if best is None else min(best, length)
print(best)
