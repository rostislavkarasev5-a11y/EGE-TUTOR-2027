"""Эталонное решение: информатика №3, задача 3 (стартовый банк, ИИ)."""

import csv
import datetime as dt


def read(name):
    with open(name, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


price = {row["Тариф"]: int(row["Цена за час"]) for row in read("i03_3_tariffs.csv")}
client = {row["Клиент"]: row for row in read("i03_3_clients.csv")}


def minutes(text):
    hours, mins = map(int, text.split(":"))
    return hours * 60 + mins


total = 0
for row in read("i03_3_visits.csv"):
    day, month, year = map(int, row["Дата"].split("."))
    who = client[row["Клиент"]]
    if who["Район"] != "Центр" or dt.date(year, month, day).weekday() < 5:
        continue
    length = minutes(row["Выход"]) - minutes(row["Вход"])
    hours = (length + 59) // 60  # неполный час считается полным
    total += hours * price[who["Тариф"]]
print(total)
