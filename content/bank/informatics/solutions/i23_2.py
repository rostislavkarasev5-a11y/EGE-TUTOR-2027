"""Эталонное решение: информатика №23, задача 2 (стартовый банк, ИИ)."""

FORBIDDEN = 30


def count(a, b):
    """Число программ из a в b командами +1, +2, ×3, траектория не проходит через 30."""
    if a == FORBIDDEN:
        return 0
    if a == b:
        return 1
    if a > b:
        return 0
    return count(a + 1, b) + count(a + 2, b) + count(a * 3, b)


print(count(3, 12) * count(12, 40))
