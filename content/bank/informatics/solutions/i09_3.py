"""Эталонное решение: информатика №9, задача 3 (стартовый банк, ИИ)."""

answer = None
with open("i09_3.csv", encoding="utf-8") as f:
    for number, line in enumerate(f, start=1):
        if not line.strip():
            continue
        row = list(map(int, line.split(";")))
        by3 = sum(1 for x in row if x % 3 == 0)
        by5 = sum(1 for x in row if x % 5 == 0)
        if max(row) - min(row) < 30 and by3 == by5:
            answer = number
print(answer)
