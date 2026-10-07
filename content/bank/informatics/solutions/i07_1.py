"""Эталонное решение: информатика №7, задача 1 (стартовый банк, ИИ)."""

bits_per_pixel = (2**16 - 1).bit_length()  # 65 536 цветов → 16 бит
size_bits = 1600 * 1200 * bits_per_pixel
print(size_bits // 8 // 1024)
assert size_bits % (8 * 1024) == 0
