"""Эталонное решение: информатика №9, задача 1 (стартовый банк, ИИ)."""

count = 0
with open("i09_1.csv", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        row = list(map(int, line.split(";")))
        if len(set(row)) == 4 and max(row) < sum(row) - max(row):
            count += 1
print(count)
