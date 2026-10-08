"""Эталонное решение: информатика №10, задача 2 (стартовый банк, ИИ)."""

import re

with open("i10_2.txt", encoding="utf-8") as f:
    words = re.findall(r"[а-яё]+", f.read().lower())
print(sum(1 for w in words if w.startswith("лес")))
