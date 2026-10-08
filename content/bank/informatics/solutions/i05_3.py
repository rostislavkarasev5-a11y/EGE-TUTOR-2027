"""Эталонное решение: информатика №5, задача 3 (стартовый банк, ИИ)."""


def R(n):
    digits = list(map(int, str(n)))
    even = sum(d for d in digits if d % 2 == 0)
    odd = sum(d for d in digits if d % 2 == 1)
    big, small = max(even, odd), min(even, odd)
    return int(f"{big}{small}")


print(sum(1 for n in range(1000, 10000) if R(n) == 1610))
