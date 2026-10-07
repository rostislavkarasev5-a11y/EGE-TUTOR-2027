"""Эталонное решение: информатика №10, задача 1 (стартовый банк, ИИ)."""

import re

with open("i10_1.txt", encoding="utf-8") as f:
    words = re.findall(r"[а-яё]+", f.read().lower())
print(words.count("мост"))
