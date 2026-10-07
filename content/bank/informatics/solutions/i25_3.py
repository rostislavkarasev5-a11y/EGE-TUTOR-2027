"""Эталонное решение: информатика №25, задача 3 (стартовый банк, ИИ)."""

from itertools import product

with open("i25_3.txt", encoding="utf-8") as f:
    mask, divisor, limit = f.read().split()
divisor, limit = int(divisor), int(limit)

fixed = len(mask) - mask.count("*")  # цифр в числе без учёта «*»
found = set()
for star_len in range(len(str(limit)) - fixed + 1):
    # «?» — ровно одна цифра, «*» — любая последовательность цифр (в том числе пустая)
    slots = mask.count("?") + mask.count("*") * star_len
    for digits in product("0123456789", repeat=slots):
        it = iter(digits)
        text = "".join(
            next(it)
            if ch == "?"
            else "".join(next(it) for _ in range(star_len))
            if ch == "*"
            else ch
            for ch in mask
        )
        if text[0] != "0" and int(text) <= limit and int(text) % divisor == 0:
            found.add(int(text))
print(len(found), max(found) // divisor)
