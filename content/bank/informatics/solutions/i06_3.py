"""Эталонное решение: информатика №6, задача 3 (стартовый банк, ИИ)."""

from itertools import pairwise


class Turtle:
    """Черепаха: начало в (0, 0), смотрит вдоль оси ординат, повороты только на 90°."""

    def __init__(self):
        self.x, self.y = 0, 0
        self.dx, self.dy = 0, 1
        self.down = True
        self.figures = [[(0, 0)]]

    def forward(self, n):
        self.x += self.dx * n
        self.y += self.dy * n
        if self.down:
            self.figures[-1].append((self.x, self.y))

    def right(self):  # Направо 90 — по часовой стрелке
        self.dx, self.dy = self.dy, -self.dx

    def left(self):  # Налево 90
        self.dx, self.dy = -self.dy, self.dx

    def pen_up(self):
        self.down = False

    def pen_down(self):
        self.down = True
        self.figures.append([(self.x, self.y)])


def on_border(px, py, poly):
    for (x1, y1), (x2, y2) in pairwise(poly):
        if min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2):
            return True  # отрезки горизонтальные или вертикальные
    return False


def inside(px, py, poly):
    """Строго внутри многоугольника (луч вправо, отрезки только вертикальные/горизонтальные)."""
    if on_border(px, py, poly):
        return False
    crossings = 0
    for (x1, y1), (x2, y2) in pairwise(poly):
        if x1 == x2 and x1 > px and min(y1, y2) <= py < max(y1, y2):
            crossings += 1
    return crossings % 2 == 1


t = Turtle()
for _ in range(3):  # Повтори 3 [Вперёд 8 Направо 90 Вперёд 4 Налево 90]
    t.forward(8)
    t.right()
    t.forward(4)
    t.left()
t.right()
t.forward(6)
t.right()
t.forward(24)
t.right()
t.forward(18)
poly = t.figures[0]
assert poly[-1] == (0, 0)
print(sum(1 for x in range(-50, 51) for y in range(-50, 51) if inside(x, y, poly)))
