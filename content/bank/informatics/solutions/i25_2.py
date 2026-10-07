"""Эталонное решение: информатика №25, задача 2 (стартовый банк, ИИ)."""

with open("i25_2.txt", encoding="utf-8") as f:
    a, b = map(int, f.read().split())


def odd_divisors(n):
    while n % 2 == 0:  # нечётные делители n — это делители нечётной части n
        n //= 2
    count, d = 0, 1
    while d * d <= n:
        if n % d == 0:
            count += 1 if d * d == n else 2
        d += 2
    return count


found = [n for n in range(a, b + 1) if odd_divisors(n) == 6]
print(len(found), max(found))
