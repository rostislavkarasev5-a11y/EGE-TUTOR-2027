"""Эталонное решение: информатика №18, задача 3 (стартовый банк, ИИ)."""

with open("i18_3.csv", encoding="utf-8") as f:
    grid = [line.strip().split(";") for line in f if line.strip()]

rows, cols = len(grid), len(grid[0])
best_max = [[None] * cols for _ in range(rows)]
best_min = [[None] * cols for _ in range(rows)]
for r in range(rows):
    for c in range(cols):
        if grid[r][c] == "#":
            continue
        value = int(grid[r][c])
        if r == 0 and c == 0:
            best_max[r][c] = best_min[r][c] = value
            continue
        # откуда Робот мог прийти в клетку (r, c)
        prev = [
            (r + dr, c + dc)
            for dr, dc in ((-1, 0), (0, -1), (-1, -1))
            if r + dr >= 0 and c + dc >= 0 and best_max[r + dr][c + dc] is not None
        ]
        if prev:
            best_max[r][c] = value + max(best_max[pr][pc] for pr, pc in prev)
            best_min[r][c] = value + min(best_min[pr][pc] for pr, pc in prev)
print(best_max[-1][-1], best_min[-1][-1])
