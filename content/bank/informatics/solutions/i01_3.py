"""Эталонное решение: информатика №1, задача 3 (стартовый банк, ИИ)."""

from itertools import permutations

# Схема дорог: буква → соседи.
GRAPH = {
    "А": "БВ",
    "Б": "АГД",
    "В": "АДЕ",
    "Г": "БЖ",
    "Д": "БВЕЖ",
    "Е": "ВДЗ",
    "Ж": "ГДЗ",
    "З": "ЕЖ",
}
# Таблица: (пункт, пункт) → длина дороги.
TABLE = {
    (1, 3): 6,
    (1, 5): 21,
    (1, 6): 8,
    (2, 4): 7,
    (2, 5): 5,
    (2, 7): 16,
    (3, 7): 10,
    (4, 8): 12,
    (5, 7): 13,
    (5, 8): 15,
    (6, 8): 9,
}

letters = sorted(GRAPH)
points = sorted({p for pair in TABLE for p in pair})
edges = {frozenset((a, b)) for a in GRAPH for b in GRAPH[a]}


def answer(weight):
    # кратчайший путь из А в З (алгоритм Дейкстры без очереди — пунктов мало)
    best = {"А": 0}
    done = set()
    while len(done) < len(best):
        v = min((d, x) for x, d in best.items() if x not in done)[1]
        done.add(v)
        for u in GRAPH[v]:
            d = best[v] + weight[frozenset((v, u))]
            if d < best.get(u, 10**9):
                best[u] = d
    return best["З"]


results = set()
for perm in permutations(letters):
    letter_of = dict(zip(points, perm, strict=True))  # пункт → буква
    mapped = {frozenset((letter_of[p], letter_of[q])): w for (p, q), w in TABLE.items()}
    if set(mapped) == edges:
        results.add(answer(mapped))
assert len(results) == 1, results  # ответ не зависит от выбора соответствия
print(results.pop())
