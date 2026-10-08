"""Эталонное решение: информатика №7, задача 2 (стартовый банк, ИИ)."""

channels, rate, depth, seconds = 2, 48_000, 24, 2 * 60 + 40
size_bytes = channels * rate * depth * seconds // 8
mb = 1024 * 1024
print(-(-size_bytes // mb))  # округление вверх
