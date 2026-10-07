"""Эталонное решение: информатика №11, задача 2 (стартовый банк, ИИ)."""

alphabet = 26 + 26 + 10 + 3
bits = (alphabet - 1).bit_length()
password_bytes = -(-15 * bits // 8)
per_user = 1200 // 40
print(per_user - password_bytes)
