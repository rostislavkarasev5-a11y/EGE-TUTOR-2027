"""Эталонное решение: информатика №9, задача 2 (стартовый банк, ИИ)."""

count = 0
with open("i09_2.csv", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        row = list(map(int, line.split(";")))
        even = [x for x in row if x % 2 == 0]
        odd = [x for x in row if x % 2 == 1]
        if len(even) == 3 and sum(even) > sum(odd) and max(row) % 2 == 1:
            count += 1
print(count)
