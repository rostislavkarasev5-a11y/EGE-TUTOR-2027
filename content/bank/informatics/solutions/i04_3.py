"""Эталонное решение: информатика №4, задача 3 (стартовый банк, ИИ)."""

from itertools import product

KNOWN = ["1", "011"]


def fano(codes):
    """Ни одно кодовое слово не является началом другого (и слова не совпадают)."""
    return all(
        not codes[j].startswith(codes[i])
        for i in range(len(codes))
        for j in range(len(codes))
        if i != j
    )


words = ["".join(p) for k in range(1, 5) for p in product("01", repeat=k)]
# В и Г — разные буквы, поэтому пара (код В, код Г) упорядочена.
print(sum(1 for v in words for g in words if fano([*KNOWN, v, g])))
