"""Эталонное решение: информатика №23, задача 3 (стартовый банк, ИИ)."""


def count(a, b, must, visited=False):
    """Программы из a в b (команды +1, ×2, ×3), не проходящие через 30;
    must — числа, хотя бы одно из которых должно встретиться в траектории."""
    if a == 30 or a > b:
        return 0
    visited = visited or a in must
    if a == b:
        return 1 if visited else 0
    return (
        count(a + 1, b, must, visited)
        + count(a * 2, b, must, visited)
        + count(a * 3, b, must, visited)
    )


print(count(2, 60, {10, 15}))
