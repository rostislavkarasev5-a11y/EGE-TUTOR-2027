"""Эталонное решение: информатика №23, задача 2 (стартовый банк, ИИ)."""

import heapq

ROADS = {
    ("A", "B"): 7,
    ("A", "C"): 3,
    ("B", "C"): 2,
    ("B", "D"): 4,
    ("C", "D"): 8,
    ("C", "E"): 6,
    ("D", "E"): 1,
    ("D", "F"): 5,
    ("E", "F"): 9,
}

graph: dict[str, list[tuple[str, int]]] = {}
for (a, b), length in ROADS.items():  # дороги двусторонние
    graph.setdefault(a, []).append((b, length))
    graph.setdefault(b, []).append((a, length))

# Алгоритм Дейкстры
best = {"A": 0}
queue = [(0, "A")]
while queue:
    dist, town = heapq.heappop(queue)
    if dist > best[town]:
        continue
    for nxt, length in graph[town]:
        if dist + length < best.get(nxt, 10**9):
            best[nxt] = dist + length
            heapq.heappush(queue, (dist + length, nxt))

print(best["F"])
