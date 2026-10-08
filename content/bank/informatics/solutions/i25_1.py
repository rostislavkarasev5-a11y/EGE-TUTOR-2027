"""Эталонное решение: информатика №25, задача 1 (стартовый банк, ИИ)."""

with open("i25_1.txt", encoding="utf-8") as f:
    a, b = map(int, f.read().split())

found = [n for n in range(a, b + 1) if n % 13 == 0 and sum(map(int, str(n))) == 30]
print(len(found), max(found))
