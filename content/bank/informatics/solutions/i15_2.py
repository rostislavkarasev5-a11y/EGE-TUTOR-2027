"""Эталонное решение: информатика №15, задача 2 (стартовый банк, ИИ)."""


def div(n, m):
    return n % m == 0


def formula(x, a):
    return div(x, a) or (not div(x, 90) and not div(x, 126))


print(max(a for a in range(1, 1001) if all(formula(x, a) for x in range(1, 5001))))
