"""Эталонное решение: информатика №26, задача 2 (стартовый банк, ИИ)."""

with open("i26_2.txt", encoding="utf-8") as f:
    n = int(f.readline())
    requests = [tuple(map(int, f.readline().split())) for _ in range(n)]

# Жадный выбор: всегда берём заявку, которая заканчивается раньше всех из подходящих.
# Он даёт и наибольшее число заявок, и самое раннее окончание последней из них.
count, last_end = 0, -1
for start, end in sorted(requests, key=lambda r: r[1]):
    if start >= last_end:
        count += 1
        last_end = end
print(count, last_end)
