"""Эталонное решение: информатика №17, задача 3 (стартовый банк, ИИ)."""

with open("i17_3.txt", encoding="utf-8") as f:
    a = [int(line) for line in f if line.strip()]

total, n = sum(a), len(a)
count, best = 0, None
for i in range(n - 3):
    x, y = a[i], a[i + 3]
    above = (x * n > total) + (y * n > total)  # сравнение со средним без дробей
    if above == 1 and (x + y) % 9 == 0:
        count += 1
        best = x + y if best is None else max(best, x + y)
print(count, best)
