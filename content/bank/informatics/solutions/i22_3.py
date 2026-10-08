"""Эталонное решение: информатика №22, задача 3 (стартовый банк, ИИ)."""

TARGET = "16"
rows = []
with open("i22_3.csv", encoding="utf-8") as f:
    next(f)  # заголовок
    for line in f:
        if line.strip():
            pid, time, deps = line.strip().split(";")
            rows.append((pid, int(time), [d for d in deps.split(",") if d != "0"]))


def total_time(extra):
    finish = {}
    for pid, time, deps in rows:
        start = max((finish[d] for d in deps), default=0)
        finish[pid] = start + time + (extra if pid == TARGET else 0)
    return max(finish.values())


base = total_time(0)
extra = 0
while total_time(extra + 1) == base:
    extra += 1
print(extra)
