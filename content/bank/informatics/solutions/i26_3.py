"""Эталонное решение: информатика №26, задача 3 (стартовый банк, ИИ)."""

import heapq

with open("i26_3.txt", encoding="utf-8") as f:
    n = int(f.readline())
    orders = [tuple(map(int, f.readline().split())) for _ in range(n)]

# Алгоритм Мура — Ходжсона: идём по срокам; если заказ опаздывает,
# выбрасываем самый длинный из взятых. Остаётся максимум заказов с наименьшим временем.
taken = []  # куча из (−длительность)
time = 0
for duration, deadline in sorted(orders, key=lambda o: o[1]):
    heapq.heappush(taken, -duration)
    time += duration
    if time > deadline:
        time += heapq.heappop(taken)
print(len(taken), time)
