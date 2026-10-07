"""Эталонное решение: информатика №2, задача 1 (стартовый банк, ИИ)."""

from itertools import permutations, product


def F(x, y, z):
    return int((x and not y) or z)


# Фрагмент таблицы: строки слева направо, None — пустая клетка; последнее число — F.
ROWS = [
    ((1, 0, 1), 0),
    ((0, 0, 0), 0),
    ((1, 0, 0), 0),
]

answers = []
for perm in permutations("xyz"):  # какая переменная стоит в каждом столбце
    blanks = [(i, j) for i, (row, _) in enumerate(ROWS) for j, v in enumerate(row) if v is None]
    for fill in product((0, 1), repeat=len(blanks)):
        table = [list(row) for row, _ in ROWS]
        for (i, j), v in zip(blanks, fill, strict=True):
            table[i][j] = v
        if len({tuple(row) for row in table}) < len(table):
            continue  # строки таблицы не должны повторяться
        if all(
            F(**dict(zip(perm, row, strict=True))) == f
            for row, (_, f) in zip(table, ROWS, strict=True)
        ):
            answers.append("".join(perm))
            break
assert len(answers) == 1, answers
print(answers[0])
