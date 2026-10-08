"""Эталонное решение: информатика №3, задача 2 (стартовый банк, ИИ)."""

import csv


def read(name):
    with open(name, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


genre = {row["Шифр"]: row["Жанр"] for row in read("i03_2_books.csv")}
reader = {row["Билет"]: row for row in read("i03_2_readers.csv")}

count = 0
for row in read("i03_2_loans.csv"):
    day, month, _ = map(int, row["Дата"].split("."))
    who = reader[row["Билет"]]
    if (
        row["Операция"] == "Выдача"
        and genre[row["Шифр"]] == "Фантастика"
        and who["Возрастная группа"] == "Школьник"
        and who["Филиал"] == "Северный"
        and month == 10
        and 1 <= day <= 20
    ):
        count += 1
print(count)
