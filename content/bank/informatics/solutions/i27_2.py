"""Эталонное решение: информатика №27, задача 2 (стартовый банк, ИИ)."""

from math import dist

R = 6  # точки на расстоянии не больше R — соседи в одном кластере

with open("i27_2.txt", encoding="utf-8") as f:
    points = [tuple(map(int, line.split())) for line in f if line.strip()]

# Раскладываем точки по квадратам R×R: соседи точки лежат в соседних квадратах.
cells = {}
for p in points:
    cells.setdefault((p[0] // R, p[1] // R), []).append(p)


def neighbours(p):
    cx, cy = p[0] // R, p[1] // R
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for q in cells.get((cx + dx, cy + dy), []):
                if q != p and dist(p, q) <= R:
                    yield q


# Кластеры — компоненты связности (обход в ширину).
seen, clusters = set(), []
for p in points:
    if p in seen:
        continue
    seen.add(p)
    queue = [p]
    for q in queue:
        for r in neighbours(q):
            if r not in seen:
                seen.add(r)
                queue.append(r)
    clusters.append(queue)


def center(cluster):
    """Точка кластера с наименьшей суммой расстояний до остальных точек кластера."""
    sums = sorted((sum(dist(p, q) for q in cluster), p) for p in cluster)
    assert sums[1][0] - sums[0][0] > 1e-6, "центр определён неоднозначно"
    return sums[0][1]


assert len(clusters) == 3, len(clusters)
clusters.sort(key=len)
assert len(clusters[0]) < len(clusters[1]) < len(clusters[2])
print(center(clusters[-1])[0], center(clusters[0])[1])
