"""Эталонное решение: информатика №21, задача 3 (стартовый банк, ИИ)."""

from functools import cache

LIMIT = 64  # игра заканчивается, когда в двух кучах вместе 64 или больше камней
FIRST = 5  # камней в первой куче
START = range(1, LIMIT - FIRST)


def moves(p):
    a, b = p
    return [(a + 2, b), (a, b + 2), (a * 2, b), (a, b * 2)]


def finished(p):
    return sum(p) >= LIMIT


def position(s):
    return (FIRST, s)


@cache
def win1(p):
    """Игрок, который ходит из p, выигрывает первым ходом."""
    return any(finished(q) for q in moves(p))


@cache
def lose1(p):
    """Ходящий проигрывает: любой его ход ведёт в позицию win1."""
    return not win1(p) and all(win1(q) for q in moves(p))


@cache
def win2(p):
    """Ходящий не выигрывает первым ходом, но гарантированно выигрывает вторым."""
    return not win1(p) and any(lose1(q) for q in moves(p))


@cache
def lose2(p):
    """Соперник выигрывает первым или вторым ходом, но не всегда первым."""
    return not win1(p) and not lose1(p) and all(win1(q) or win2(q) for q in moves(p))


answer = [s for s in START if lose2(position(s))]
print(min(answer))
