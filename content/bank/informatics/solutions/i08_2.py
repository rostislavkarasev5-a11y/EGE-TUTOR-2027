"""Эталонное решение: информатика №8, задача 2 (стартовый банк, ИИ)."""

from itertools import pairwise, product

VOWELS = "АУ"
count = 0
for w in product("ПАРУС", repeat=6):
    if w[0] in VOWELS:
        continue
    if any(a in VOWELS and b in VOWELS for a, b in pairwise(w)):
        continue
    count += 1
print(count)
