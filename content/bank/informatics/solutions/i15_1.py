"""Эталонное решение: информатика №15, задача 1 (стартовый банк, ИИ)."""

P = (15, 40)
Q = (30, 65)
xs = [i / 4 for i in range(0, 401)]  # точки с шагом 0,25 на отрезке [0; 100]


def inside(x, seg):
    return seg[0] <= x <= seg[1]


def formula_true(a):
    return all((not inside(x, P) or inside(x, Q)) or inside(x, a) for x in xs)


ends = [i / 2 for i in range(0, 201)]  # концы A с шагом 0,5
best = min(b - a for a in ends for b in ends if a <= b and formula_true((a, b)))
print(int(best) if best == int(best) else best)
