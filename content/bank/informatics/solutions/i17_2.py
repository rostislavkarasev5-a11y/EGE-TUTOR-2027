"""Эталонное решение: информатика №17, задача 2 (стартовый банк, ИИ)."""

with open("i17_2.txt", encoding="utf-8") as f:
    a = [int(line) for line in f if line.strip()]


def two_digit(x):
    return 10 <= abs(x) <= 99


m = max(x for x in a if two_digit(x) and abs(x) % 10 == 7)


count, best = 0, None
for i in range(len(a) - 2):
    triple = a[i : i + 3]
    if sum(map(two_digit, triple)) == 2 and sum(triple) > 0 and sum(triple) % m == 0:
        count += 1
        best = sum(triple) if best is None else max(best, sum(triple))
print(count, best)
