"""Эталонное решение: информатика №23, задача 1 (стартовый банк, ИИ)."""


def count(a, b):
    """Число программ, переводящих a в b командами +1, +3, ×2."""
    if a == b:
        return 1
    if a > b:
        return 0
    return count(a + 1, b) + count(a + 3, b) + count(a * 2, b)


print(count(2, 21))
