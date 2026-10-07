"""Эталонное решение: информатика №12, задача 2 (стартовый банк, ИИ)."""

s = "1" * 95
while "11" in s or "222" in s or "13" in s:
    if "11" in s:
        s = s.replace("11", "2", 1)
    elif "222" in s:
        s = s.replace("222", "13", 1)
    else:
        s = s.replace("13", "3", 1)
print(sum(map(int, s)))
