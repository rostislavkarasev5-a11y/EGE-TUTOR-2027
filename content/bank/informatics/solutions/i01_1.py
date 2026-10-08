"""Эталонное решение: информатика №1, задача 1 (стартовый банк, ИИ)."""

from itertools import permutations

# Схема дорог: буква → соседи.
GRAPH = {
    "А": "БВ",
    "Б": "АВГ",
    "В": "АБД",
    "Г": "БДЕ",
    "Д": "ВГ",
    "Е": "Г",
}
# Таблица: (пункт, пункт) → длина дороги.
TABLE = {
    (1, 3): 14,
    (1, 6): 9,
    (2, 5): 7,
    (2, 6): 11,
    (3, 4): 5,
    (3, 5): 12,
    (5, 6): 6,
}

letters = sorted(GRAPH)
points = sorted({p for pair in TABLE for p in pair})
edges = {frozenset((a, b)) for a in GRAPH for b in GRAPH[a]}


def answer(weight):
    return weight[frozenset("БГ")]


results = set()
for perm in permutations(letters):
    letter_of = dict(zip(points, perm, strict=True))  # пункт → буква
    mapped = {frozenset((letter_of[p], letter_of[q])): w for (p, q), w in TABLE.items()}
    if set(mapped) == edges:
        results.add(answer(mapped))
assert len(results) == 1, results  # ответ не зависит от выбора соответствия
print(results.pop())
