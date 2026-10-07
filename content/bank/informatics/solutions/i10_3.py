"""Эталонное решение: информатика №10, задача 3 (стартовый банк, ИИ)."""

import re

with open("i10_3.txt", encoding="utf-8") as f:
    words = re.findall(r"[а-яё]+", f.read().lower())
print(sum(1 for w in words if "вод" in w and not w.startswith("вод")))
