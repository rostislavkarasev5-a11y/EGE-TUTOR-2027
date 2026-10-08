"""Проверка стартового банка по профильной математике (ADR-0016).

Каждый ответ ещё раз вычисляется с нуля — SymPy, точные дроби или перебор — без чтения
ключа из YAML, и только потом сравнивается с ключом. Расхождение означает, что задача
неверна (DISPUTED), и исправлять нужно задачу, а не проверку.
"""

import itertools
from collections.abc import Callable
from fractions import Fraction as F

import pytest
import sympy as sp
import yaml

from ege_tutor.core.domain import TaskSource
from tests.conftest import REPO_ROOT

BANK = REPO_ROOT / "content" / "bank" / "math_profile.yaml"
REF = "EGE-TUTOR-2027, стартовый банк: математика №{item}, задача {n}"
TOL = sp.Rational(1, 10**9)

x, t, a = sp.symbols("x t a", real=True)


def _load() -> dict:
    return yaml.safe_load(BANK.read_text(encoding="utf-8"))


def _tasks() -> list[dict]:
    data = _load()
    defaults = data.get("defaults") or {}
    return [{**defaults, **task} for task in data["tasks"]]


def _parse_answer(value) -> list[sp.Rational]:
    """Ключ из YAML → список точных чисел («0,4» → 2/5, «-2; 3» → [−2, 3])."""
    parts = str(value).replace("−", "-").split(";")
    return [sp.Rational(p.strip().replace(",", ".")) for p in parts]


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


# ── независимые проверки ────────────────────────────────────────────────────


def _dist_point_plane(p, p1, p2, p3):
    p, p1, p2, p3 = (sp.Matrix(v) for v in (p, p1, p2, p3))
    n = (p2 - p1).cross(p3 - p1)
    return sp.Abs(n.dot(p - p1)) / n.norm()


def m1_1():
    return sp.sqrt(9**2 + 40**2)


def m1_2():
    h = sp.sqrt(10**2 - sp.Rational(19 - 7, 2) ** 2)
    a_, b_, c_, d_ = (0, 0), (6, h), (13, h), (19, 0)  # трапеция по координатам
    assert sp.sqrt((b_[0] - a_[0]) ** 2 + (b_[1] - a_[1]) ** 2) == 10
    return sp.Polygon(a_, b_, c_, d_).area.__abs__()


def m1_3():
    tri = sp.Triangle(sp.Point(0, 0), sp.Point(14, 0), sp.Point(5, 12))
    sides = sorted(s.length for s in tri.sides)
    assert sides == [13, 14, 15]
    return tri.inradius


def m2_1():
    return (sp.Matrix([7, -2]) + sp.Matrix([-4, 6])).norm()


def m2_2():
    va, vb = sp.Matrix([4, -1]), sp.Matrix([2, 3])
    return (va + 2 * vb).dot(va - vb)


def m2_3():
    ang = sp.rad(120)
    va = sp.Matrix([5, 0])
    vb = sp.Matrix([3 * sp.cos(ang), 3 * sp.sin(ang)])
    return sp.nsimplify((va - vb).norm())


def m3_1():
    return sp.sqrt(2**2 + 6**2 + 9**2)


def m3_2():
    s, h = sp.symbols("s h", positive=True)
    sh = sp.solve(sp.Eq(s * h / 3, 24), s)[0] * h  # S·h из объёма конуса
    return sp.simplify(sh * 2)


def m3_3():
    h = sp.sqrt(13**2 - 5**2)
    return sp.Rational(1, 3) * 10**2 * h


def m4_1():
    return sp.Rational(8, 25)


def m4_2():
    outcomes = list(itertools.product("ОР", repeat=3))
    good = [o for o in outcomes if o.count("О") == 2]
    return sp.Rational(len(good), len(outcomes))


def m4_3():
    people = ["Ю"] * 10 + ["Д"] * 6
    pairs = list(itertools.combinations(range(len(people)), 2))
    good = [p for p in pairs if people[p[0]] != people[p[1]]]
    return sp.Rational(len(good), len(pairs))


def m5_1():
    p = F(8, 10)
    return p * (1 - p)


def m5_2():
    p1, p2 = F(90, 100), F(85, 100)
    # перебор всех состояний двух автоматов
    total = F(0)
    for s1, s2 in itertools.product([True, False], repeat=2):
        pr = (p1 if s1 else 1 - p1) * (p2 if s2 else 1 - p2)
        if s1 or s2:
            total += pr
    return total


def m5_3():
    share = {1: F(60, 100), 2: F(40, 100)}
    defect = {1: F(2, 100), 2: F(5, 100)}
    p_def = sum(share[k] * defect[k] for k in share)
    return share[2] * defect[2] / p_def


def m6_1():
    return sp.solve(sp.Eq(7 ** (x - 2), 49), x)


def m6_2():
    roots = sp.solve(sp.Eq(sp.sqrt(2 * x + 19), x + 2), x)
    return max(roots)


def m6_3():
    return sp.solve(sp.Eq(sp.log(x + 3, 2) + sp.log(x - 1, 2), 5), x)


def m7_1():
    return sp.Integer(12) ** 7 / (sp.Integer(4) ** 6 * sp.Integer(3) ** 7)


def m7_2():
    return sp.simplify(sp.log(75, 5) - sp.log(3, 5) + 9 ** sp.log(4, 3))


def m7_3():
    alpha = sp.symbols("alpha")
    sols = sp.solve(sp.Eq(sp.cos(alpha), sp.Rational(-5, 13)), alpha)
    sols = [s % (2 * sp.pi) for s in sols]
    good = [s for s in sols if sp.pi < s < 3 * sp.pi / 2]
    assert len(good) == 1
    return sp.nsimplify(sp.tan(good[0]))


def m8_1():
    return sp.diff(t**3 - 4 * t**2 + 5 * t, t).subs(t, 3)


def m8_2():
    f = x**2 - 5 * x + 7
    (x0,) = sp.solve(sp.Eq(sp.diff(f, x), 3), x)
    return f.subs(x, x0)


def m8_3():
    f = -(x**2) + 4 * x + 5
    lo, hi = sorted(sp.solve(f, x))
    assert f.subs(x, (lo + hi) / 2) > 0
    return sp.integrate(f, (x, lo, hi))


def m9_1():
    return sp.solve(sp.Eq(sp.Rational(18, 10) * x + 32, 113), x)


def m9_2():
    h = sp.Rational(14, 10) + 14 * t - 5 * t**2
    s = sp.solve_univariate_inequality(h >= sp.Rational(94, 10), t, relational=False)
    return s.measure


def m9_3():
    d1, d2 = sp.symbols("d1 d2", positive=True)
    f = 30
    d1_of_d2 = sp.solve(sp.Eq(1 / d1 + 1 / d2, sp.Rational(1, f)), d1)[0]
    # при d₂ > f функция d₁(d₂) убывает, значит минимум d₁ на d₂ ∈ (f; 150] — при d₂ = 150
    assert sp.diff(d1_of_d2, d2).subs(d2, 100) < 0
    values = [d1_of_d2.subs(d2, v) for v in range(31, 151)]
    assert min(values) == d1_of_d2.subs(d2, 150)
    return d1_of_d2.subs(d2, 150)


def m10_1():
    price = F(40) * F(115, 100)
    return F(920) / price


def m10_2():
    v = sp.symbols("v", positive=True)
    roots = sp.solve(sp.Eq(48 / (v + 2) + 48 / (v - 2), 7), v)
    return [r for r in roots if r > 2]


def m10_3():
    y = sp.symbols("y", positive=True)
    roots = sp.solve(sp.Eq(1 / y + 1 / (y - 5), sp.Rational(1, 6)), y)
    return [r for r in roots if r > 5]


def m11_1():
    k, b = sp.symbols("k b")
    sol = sp.solve([sp.Eq(-k + b, 7), sp.Eq(3 * k + b, -5)], [k, b])
    return sol[k] * 10 + sol[b]


def m11_2():
    pa, pb, pc = sp.symbols("pa pb pc")
    f = pa * x**2 + pb * x + pc
    sol = sp.solve([f.subs(x, 0) - 3, f.subs(x, 1), f.subs(x, 2) + 1], [pa, pb, pc])
    return f.subs(sol).subs(x, 5)


def m11_3():
    k, s = sp.symbols("k s")
    sols = sp.solve([sp.Eq(k / (1 + s), 2), sp.Eq(k / (3 + s), 1)], [k, s], dict=True)
    (sol,) = sols
    return (k / (x + s)).subs(sol).subs(x, 9)


def _extreme_on(f, lo, hi, kind):
    crit = [c for c in sp.solve(sp.diff(f, x), x) if c.is_real and lo <= c <= hi]
    values = [f.subs(x, p) for p in [lo, hi, *crit]]
    return sp.simplify(max(values) if kind == "max" else min(values))


def m12_1():
    f = x**3 - 12 * x + 5
    d2 = sp.diff(f, x, 2)
    return [c for c in sp.solve(sp.diff(f, x), x) if d2.subs(x, c) > 0]


def m12_2():
    return _extreme_on(x**3 - 3 * x**2 - 9 * x + 4, -2, 2, "max")


def m12_3():
    return _extreme_on((x - 6) * sp.exp(x - 5), 3, 7, "min")


def _roots_on(expr, lo, hi) -> list:
    roots = sp.solveset(expr, x, sp.Interval(lo, hi))
    assert isinstance(roots, sp.FiniteSet), roots
    for r in roots:
        assert abs(sp.N(expr.subs(x, r), 30)) < 1e-20
    return sorted(roots, key=lambda r: float(r))


def m13_1():
    return len(_roots_on(2 * sp.sin(x) ** 2 + sp.sin(x) - 1, -2 * sp.pi, sp.pi))


def m13_2():
    return _roots_on(4**x - 5 * 2 ** (x + 1) + 16, sp.log(5, 2), 4)


def m13_3():
    roots = _roots_on(sp.sin(2 * x) - sp.sqrt(3) * sp.cos(x), -5 * sp.pi / 2, -sp.pi)
    return sp.simplify(sum(roots) * 180 / sp.pi)


def m14_1():
    A, B, C = (0, 0, 0), (6, 0, 0), (6, 8, 0)
    C1 = (6, 8, 5)
    return _dist_point_plane(B, A, C, C1)


def m14_2():
    s3 = sp.sqrt(3)
    A, B = sp.Matrix([0, 0, 0]), sp.Matrix([6, 0, 0])
    B1, C1 = sp.Matrix([6, 0, 6]), sp.Matrix([3, 3 * s3, 6])
    u, w = B1 - A, C1 - B
    assert (B - A).norm() == (sp.Matrix([3, 3 * s3, 0]) - B).norm() == 6
    return sp.simplify(sp.Abs(u.dot(w)) / (u.norm() * w.norm()))


def m14_3():
    A, B, C, S = (-8, -8, 0), (8, -8, 0), (8, 8, 0), (0, 0, 6)
    return sp.simplify(_dist_point_plane(A, S, B, C))


def _integer_solutions(pred, lo=-200, hi=200) -> list[int]:
    sols = [n for n in range(lo, hi + 1) if pred(n)]
    # множество решений ограничено: на краях диапазона решений нет
    assert lo not in sols and hi not in sols
    return sols


def m15_1():
    def pred(n):
        if n == 6:
            return False
        return F(n * n - n - 12, (n - 6) ** 2) <= 0

    return len(_integer_solutions(pred))


def m15_2():
    def pred(n):
        p = F(2) ** n
        return p * p - 9 * p + 8 <= 0

    return sum(_integer_solutions(pred))


def m15_3():
    def pred(n):
        u, v = n * n - 4 * n, n + 6
        if u <= 0 or v <= 0:
            return False
        diff = sp.log(u, 3) - sp.log(v, 3)
        return sp.N(diff, 50) <= sp.Float("1e-40")

    return sum(_integer_solutions(pred, -50, 50))


def m16_1():
    debt, n, rate = F(1_200_000), 10, F(2, 100)
    step = debt / n
    paid = F(0)
    for k in range(1, n + 1):
        debt *= 1 + rate
        target = F(1_200_000) - step * k
        paid += debt - target
        debt = target
    assert debt == 0
    return paid


def m16_2():
    def final(x_):
        s = F(1000)
        for year in range(1, 5):
            s *= F(11, 10)
            if year <= 2:
                s += x_
        return s

    return next(x_ for x_ in range(0, 2000) if final(x_) >= 2000)


def m16_3():
    s, p = sp.symbols("s p")
    payment = sp.Rational(2_662_000, 2)
    debt = s
    for pay in (p, p, 2 * p):
        debt = debt * sp.Rational(11, 10) - pay
    return sp.solve(debt.subs(p, payment), s)


def m17_1():
    tri = sp.Triangle(sp.Point(15, 0), sp.Point(0, 20), sp.Point(0, 0))  # A, B, C
    alt = tri.altitudes[sp.Point(0, 0)]
    return alt.length


def m17_2():
    h = sp.Rational(2 * 64, 12 + 4)
    A, D, B, C = (sp.Point(*p) for p in [(0, 0), (12, 0), (2, h), (6, h)])
    assert sp.Polygon(A, B, C, D).area.__abs__() == 64
    (cross,) = sp.Segment(A, C).intersection(sp.Segment(B, D))
    return abs(sp.Triangle(A, cross, D).area)


def m17_3():
    B, C = sp.Point(0, 0), sp.Point(14, 0)
    px, py = sp.symbols("px py", real=True)
    sols = sp.solve([px**2 + py**2 - 169, (px - 14) ** 2 + py**2 - 225], [px, py], dict=True)
    sol = next(s for s in sols if s[py] > 0)
    A = sp.Point(sol[px], sol[py])
    tri = sp.Triangle(A, B, C)
    K = sp.Line(B, C).projection(tri.incenter)
    H = sp.Line(B, C).projection(A)
    return K.distance(H)


def _real_roots(expr) -> set:
    return {r for r in sp.solve(expr, x) if r.is_real}


def m18_1():
    poly = sp.Poly(x**2 - 2 * a * x + a + 6, x)
    return sorted(sp.solve(sp.discriminant(poly, x), a))


def m18_2():
    good = []
    for av in range(-30, 31):
        roots = _real_roots(x**2 - 4 * x - av) | _real_roots(x**2 - 4 * x + av)
        roots = {r for r in roots if sp.simplify(sp.Abs(r**2 - 4 * r) - av) == 0}
        if len(roots) == 4:
            good.append(av)
    return good


def m18_3():
    good = []
    for av in range(-30, 31):
        under_root = (5 - x) * (x + 3)
        expr = (x - av) * (x - 2 * av) * under_root  # нули с корнем те же, что и с его квадратом
        roots = {r for r in _real_roots(expr) if under_root.subs(x, r) >= 0}
        if len(roots) == 4:
            good.append(av)
    return good


def m19_1():
    return next(n for n in range(1, 10_000) if n % 5 == 3 and n % 7 == 4 and n % 9 == 2)


def m19_2():
    # рюкзак 0/1: наибольшее количество различных натуральных чисел с суммой ровно 100
    best = [None] * 101
    best[0] = 0
    for num in range(1, 101):
        for s in range(100, num - 1, -1):
            if best[s - num] is not None and (best[s] is None or best[s - num] + 1 > best[s]):
                best[s] = best[s - num] + 1
    return best[100]


def m19_3():
    nums = list(range(1, 21))
    conflict = {n: {m for m in nums if m != n and (n + m) % 7 == 0} for n in nums}

    def mis(candidates: frozenset) -> int:
        if not candidates:
            return 0
        v = max(candidates, key=lambda u: len(conflict[u] & candidates))
        if not conflict[v] & candidates:
            return len(candidates)  # конфликтов не осталось — берём всё
        without_v = mis(candidates - {v})
        with_v = 1 + mis(candidates - {v} - conflict[v])
        return max(without_v, with_v)

    return mis(frozenset(nums))


CHECKS: dict[str, Callable] = {
    REF.format(item=1, n=1): m1_1,
    REF.format(item=1, n=2): m1_2,
    REF.format(item=1, n=3): m1_3,
    REF.format(item=2, n=1): m2_1,
    REF.format(item=2, n=2): m2_2,
    REF.format(item=2, n=3): m2_3,
    REF.format(item=3, n=1): m3_1,
    REF.format(item=3, n=2): m3_2,
    REF.format(item=3, n=3): m3_3,
    REF.format(item=4, n=1): m4_1,
    REF.format(item=4, n=2): m4_2,
    REF.format(item=4, n=3): m4_3,
    REF.format(item=5, n=1): m5_1,
    REF.format(item=5, n=2): m5_2,
    REF.format(item=5, n=3): m5_3,
    REF.format(item=6, n=1): m6_1,
    REF.format(item=6, n=2): m6_2,
    REF.format(item=6, n=3): m6_3,
    REF.format(item=7, n=1): m7_1,
    REF.format(item=7, n=2): m7_2,
    REF.format(item=7, n=3): m7_3,
    REF.format(item=8, n=1): m8_1,
    REF.format(item=8, n=2): m8_2,
    REF.format(item=8, n=3): m8_3,
    REF.format(item=9, n=1): m9_1,
    REF.format(item=9, n=2): m9_2,
    REF.format(item=9, n=3): m9_3,
    REF.format(item=10, n=1): m10_1,
    REF.format(item=10, n=2): m10_2,
    REF.format(item=10, n=3): m10_3,
    REF.format(item=11, n=1): m11_1,
    REF.format(item=11, n=2): m11_2,
    REF.format(item=11, n=3): m11_3,
    REF.format(item=12, n=1): m12_1,
    REF.format(item=12, n=2): m12_2,
    REF.format(item=12, n=3): m12_3,
    REF.format(item=13, n=1): m13_1,
    REF.format(item=13, n=2): m13_2,
    REF.format(item=13, n=3): m13_3,
    REF.format(item=14, n=1): m14_1,
    REF.format(item=14, n=2): m14_2,
    REF.format(item=14, n=3): m14_3,
    REF.format(item=15, n=1): m15_1,
    REF.format(item=15, n=2): m15_2,
    REF.format(item=15, n=3): m15_3,
    REF.format(item=16, n=1): m16_1,
    REF.format(item=16, n=2): m16_2,
    REF.format(item=16, n=3): m16_3,
    REF.format(item=17, n=1): m17_1,
    REF.format(item=17, n=2): m17_2,
    REF.format(item=17, n=3): m17_3,
    REF.format(item=18, n=1): m18_1,
    REF.format(item=18, n=2): m18_2,
    REF.format(item=18, n=3): m18_3,
    REF.format(item=19, n=1): m19_1,
    REF.format(item=19, n=2): m19_2,
    REF.format(item=19, n=3): m19_3,
}


# ── тесты ───────────────────────────────────────────────────────────────────


def test_bank_structure():
    tasks = _tasks()
    assert len(tasks) == 57
    refs = [task["source_ref"] for task in tasks]
    assert len(set(refs)) == len(refs)
    for item in range(1, 20):
        of_item = [task for task in tasks if task["exam_item"] == item]
        assert sorted(task["difficulty"] for task in of_item) == [2, 3, 4], item
        for task in of_item:
            n = task["difficulty"] - 1  # задача 1 — сложность 2, задача 3 — сложность 4
            assert task["source_ref"] == REF.format(item=item, n=n)
    for task in tasks:
        assert task["source"] == TaskSource.AI_GENERATED.value
        assert task["subject"] == "math"
        assert task["solution"].strip()
        assert 2 <= len(task["hints"]) <= 3
        assert 1 <= len(task["skills"]) <= 2
        assert "answer_type" not in task  # тип ответа выводит импорт из спецификации


def test_checks_cover_every_task():
    assert set(CHECKS) == {task["source_ref"] for task in _tasks()}


@pytest.mark.parametrize("ref", sorted(CHECKS))
def test_answer_recomputed(ref):
    task = next(task for task in _tasks() if task["source_ref"] == ref)
    computed = [sp.nsimplify(sp.sympify(v)) for v in _as_list(CHECKS[ref]())]
    expected = _parse_answer(task["answer"])
    assert len(computed) == len(expected), (computed, expected)
    for got, want in zip(computed, expected, strict=True):
        assert abs(sp.N(got - want, 30)) < TOL, (ref, computed, expected)
    if len(expected) > 1:
        assert expected == sorted(expected)


def test_bank_imports_cleanly(tutor):
    # обычный импорт не пускает задачи от ИИ со статусом REVIEWED — только стартовый банк
    assert tutor.preview_import(BANK).accepted == []
    report = tutor.preview_import(BANK, starter_bank=True)
    assert report.errors == []
    assert report.warnings == []
    assert len(report.accepted) == 57
    assert report.rejected_rows == set()
