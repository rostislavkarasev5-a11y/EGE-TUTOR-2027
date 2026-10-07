"""Эталонное решение: информатика №5, задача 2 (стартовый банк, ИИ)."""


def ternary(n):
    s = ""
    while n > 0:
        s = str(n % 3) + s
        n //= 3
    return s


def R(n):
    s = ternary(n)
    if n % 3 == 0:
        s += s[-2:]
    else:
        s += str(sum(map(int, s)) % 3)
    return int(s, 3)


n = 1
while R(n) <= 300:
    n += 1
print(n)
