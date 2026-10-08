"""Эталонное решение: информатика №13, задача 2 (стартовый банк, ИИ)."""

from ipaddress import ip_address, ip_interface

target = ip_address("118.46.144.0")
count = sum(
    1
    for prefix in range(33)
    if ip_interface(f"118.46.147.29/{prefix}").network.network_address == target
)
print(count)
