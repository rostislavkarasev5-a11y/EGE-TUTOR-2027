"""Эталонное решение: информатика №15, задача 3 (стартовый банк, ИИ)."""


def formula(x, a):
    return (x & 53 == 0) or (x & 41 != 0) or (x & a != 0)


print(min(a for a in range(256) if all(formula(x, a) for x in range(1024))))
