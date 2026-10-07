"""Эталонное решение: информатика №13, задача 3 (стартовый банк, ИИ)."""

from ipaddress import ip_network

net = ip_network("203.88.164.0/255.255.252.0")
print(sum(1 for address in net if bin(int(address)).count("1") % 5 == 0))
