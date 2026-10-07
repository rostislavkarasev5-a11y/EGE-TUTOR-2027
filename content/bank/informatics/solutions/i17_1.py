"""Эталонное решение: информатика №17, задача 1 (стартовый банк, ИИ)."""

from itertools import pairwise

with open("i17_1.txt", encoding="utf-8") as f:
    a = [int(line) for line in f if line.strip()]

count, best = 0, None
for x, y in pairwise(a):
    if x % 7 == 0 and y % 7 == 0 and x + y > 0:
        count += 1
        best = x + y if best is None else max(best, x + y)
print(count, best)
