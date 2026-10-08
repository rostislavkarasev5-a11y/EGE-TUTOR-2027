"""Эталонное решение: информатика №12, задача 3 (стартовый банк, ИИ)."""


def run(s):
    while "25" in s or "355" in s or "555" in s:
        if "25" in s:
            s = s.replace("25", "3", 1)
        elif "355" in s:
            s = s.replace("355", "52", 1)
        else:
            s = s.replace("555", "23", 1)
    return s


n = 51
while sum(map(int, run("2" + "5" * n))) != 19:
    n += 1
print(n)
