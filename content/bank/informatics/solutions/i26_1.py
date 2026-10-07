"""Эталонное решение: информатика №26, задача 1 (стартовый банк, ИИ)."""

with open("i26_1.txt", encoding="utf-8") as f:
    capacity, n = map(int, f.readline().split())
    masses = sorted(int(f.readline()) for _ in range(n))

count = 0
total = 0
for m in masses:
    if total + m > capacity:
        break
    total += m
    count += 1
print(count, capacity - total)
