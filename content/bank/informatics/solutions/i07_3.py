"""Эталонное решение: информатика №7, задача 3 (стартовый банк, ИИ)."""

channel_bits = 256_000 * 3 * 60  # передано за 3 минуты
pixels = 640 * 480
bits = 1
# после сжатия размер изображения — 75 % от исходного: 25 · pixels · bits · 3/4 ≤ channel_bits
while 25 * pixels * (bits + 1) * 3 <= channel_bits * 4:
    bits += 1
print(2**bits)
