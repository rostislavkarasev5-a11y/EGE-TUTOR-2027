"""Эталонное решение: информатика №8, задача 3 (стартовый банк, ИИ)."""

from itertools import pairwise, product

count = 0
for digits in product(range(7), repeat=6):  # шестизначные числа в семеричной системе
    if digits[0] == 0 or digits.count(5) != 1:
        continue
    if any(a % 2 == 1 and b % 2 == 1 for a, b in pairwise(digits)):
        continue
    count += 1
print(count)
