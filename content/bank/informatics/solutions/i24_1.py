"""Эталонное решение: информатика №24, задача 1 (стартовый банк, ИИ)."""

with open("i24_1.txt", encoding="utf-8") as f:
    s = f.read().strip()

best = current = 0
for ch in s:
    current = current + 1 if ch in "XY" else 0
    best = max(best, current)
print(best)
