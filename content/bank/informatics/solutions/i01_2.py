"""Эталонное решение: информатика №1, задача 2 (стартовый банк, ИИ)."""

from itertools import permutations

# Схема дорог: буква → соседи.
GRAPH = {
    "А": "БВГ",
    "Б": "АВД",
    "В": "АБЕ",
    "Г": "АЕ",
    "Д": "БЖ",
    "Е": "ВГЖ",
    "Ж": "ДЕ",
}
# Таблица: (пункт, пункт) → длина дороги.
TABLE = {
    (1, 2): 11,
    (1, 4): 15,
    (1, 7): 9,
    (2, 6): 6,
    (3, 5): 8,
    (3, 6): 17,
    (3, 7): 4,
    (4, 5): 10,
    (5, 7): 13,
}

letters = sorted(GRAPH)
points = sorted({p for pair in TABLE for p in pair})
edges = {frozenset((a, b)) for a in GRAPH for b in GRAPH[a]}


def answer(weight):
    return weight[frozenset("БД")] + weight[frozenset("ГЕ")]


results = set()
for perm in permutations(letters):
    letter_of = dict(zip(points, perm, strict=True))  # пункт → буква
    mapped = {frozenset((letter_of[p], letter_of[q])): w for (p, q), w in TABLE.items()}
    if set(mapped) == edges:
        results.add(answer(mapped))
assert len(results) == 1, results  # ответ не зависит от выбора соответствия
print(results.pop())
