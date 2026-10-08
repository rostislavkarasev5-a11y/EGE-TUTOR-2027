"""Эталонное решение: информатика №14, задача 3 (стартовый банк, ИИ)."""

DIGITS = "0123456789ABCDEF"
found = []
for x in DIGITS:
    for y in DIGITS:
        total = int(f"8{x}31{y}", 16) + int(f"2{y}{x}7", 16)
        if total % 89 == 0:
            found.append(total)
print(min(found) // 89)
