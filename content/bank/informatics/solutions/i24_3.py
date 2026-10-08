"""Эталонное решение: информатика №24, задача 3 (стартовый банк, ИИ)."""

with open("i24_3.txt", encoding="utf-8") as f:
    s = f.read().strip()

# balance = (число A) − (число B) в префиксе; равные балансы дают подстроку с A = B
first = {0: 0}
balance = best = 0
for i, ch in enumerate(s, start=1):
    balance += (ch == "A") - (ch == "B")
    if balance in first:
        best = max(best, i - first[balance])
    else:
        first[balance] = i
print(best)
