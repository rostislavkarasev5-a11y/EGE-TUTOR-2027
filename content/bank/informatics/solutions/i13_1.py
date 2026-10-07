"""Эталонное решение: информатика №13, задача 1 (стартовый банк, ИИ)."""

from ipaddress import ip_interface

net = ip_interface("172.19.205.77/255.255.240.0").network
print(str(net.network_address).split(".")[2])
