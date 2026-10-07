"""Эталонное решение: информатика №21, задача 1 (стартовый банк, ИИ)."""

from functools import cache

LIMIT = 41  # игра заканчивается, когда в куче 41 или больше камней
START = range(1, 41)


def moves(p):
    return [p + 1, p + 2, p * 2]


def finished(p):
    return p >= LIMIT


def position(s):
    return s


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
