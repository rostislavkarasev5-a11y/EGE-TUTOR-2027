"""Эталонное решение: информатика №22, задача 2 (стартовый банк, ИИ)."""

start, finish = {}, {}
with open("i22_2.csv", encoding="utf-8") as f:
    next(f)  # заголовок
    for line in f:
        if not line.strip():
            continue
        pid, time, deps = line.strip().split(";")
        start[pid] = max((finish[d] for d in deps.split(",") if d != "0"), default=0)
        finish[pid] = start[pid] + int(time)

# Процесс выполняется в промежутке [начало; конец): в момент конца он уже не идёт.
best = max(sum(1 for p in start if start[p] <= t < finish[p]) for t in start.values())
print(best)
