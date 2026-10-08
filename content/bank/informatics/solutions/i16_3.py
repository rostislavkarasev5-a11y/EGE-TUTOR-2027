"""Эталонное решение: информатика №16, задача 3 (стартовый банк, ИИ)."""

F = {}
for n in range(1, 501):
    if n <= 2:
        F[n] = n
    elif n % 3 == 0:
        F[n] = F[n - 1] + F[n - 2]
    else:
        F[n] = F[n - 2] + n
print(sum(1 for n in F if F[n] % 9 == 0))
