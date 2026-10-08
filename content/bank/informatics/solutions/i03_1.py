"""Эталонное решение: информатика №3, задача 1 (стартовый банк, ИИ)."""

import csv

with open("i03_1_goods.csv", encoding="utf-8") as f:
    category = {row["Артикул"]: row["Категория"] for row in csv.DictReader(f, delimiter=";")}

total = 0
with open("i03_1_sales.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter=";"):
        day, month, _ = map(int, row["Дата"].split("."))
        if category[row["Артикул"]] == "Канцтовары" and month == 3 and 5 <= day <= 12:
            total += int(row["Количество"])
print(total)
