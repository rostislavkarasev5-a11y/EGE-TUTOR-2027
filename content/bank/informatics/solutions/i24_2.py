"""Эталонное решение: информатика №24, задача 2 (стартовый банк, ИИ)."""

with open("i24_2.txt", encoding="utf-8") as f:
    s = f.read().strip()

best = left = z_count = 0
for right, ch in enumerate(s):
    z_count += ch == "Z"
    while z_count > 3:  # сдвигаем левую границу окна
        z_count -= s[left] == "Z"
        left += 1
    best = max(best, right - left + 1)
print(best)
