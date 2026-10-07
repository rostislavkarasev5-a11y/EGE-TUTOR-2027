"""Эталонное решение: информатика №22, задача 1 (стартовый банк, ИИ)."""

finish = {}
with open("i22_1.csv", encoding="utf-8") as f:
    next(f)  # заголовок
    for line in f:
        if not line.strip():
            continue
        pid, time, deps = line.strip().split(";")
        start = max((finish[d] for d in deps.split(",") if d != "0"), default=0)
        finish[pid] = start + int(time)
print(max(finish.values()))
