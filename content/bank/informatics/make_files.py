"""Генератор файлов к стартовому банку задач по информатике (ADR-0016).

Все файлы в папке files/ создаёт только этот скрипт: у каждого файла свой фиксированный
seed, поэтому результат одинаков на любом компьютере. Тест
tests/content/test_bank_informatics.py заново генерирует файлы во временную папку и
сравнивает их побайтно с файлами в репозитории.

Запуск (из корня репозитория):
    uv run python content/bank/informatics/make_files.py            # записать в files/
    uv run python content/bank/informatics/make_files.py --out DIR  # записать в другую папку

Данные выдуманы: это не задания ФИПИ и не задачи из сборников.
"""

import argparse
import datetime as dt
import random
from collections.abc import Callable
from pathlib import Path

FILES_DIR = Path(__file__).resolve().parent / "files"

Generator = Callable[[random.Random], dict[str, list[str]]]
_GENERATORS: dict[int, Generator] = {}


def _seed(seed: int) -> Callable[[Generator], Generator]:
    """Зарегистрировать генератор со своим seed."""

    def wrap(func: Generator) -> Generator:
        _GENERATORS[seed] = func
        return func

    return wrap


# ── №3: связанные таблицы (вместо электронной таблицы — CSV) ─────────────────


@_seed(301)
def _i03_1(rng: random.Random) -> dict[str, list[str]]:
    categories = {
        "Канцтовары": ["Тетрадь", "Ручка", "Карандаш", "Ластик", "Линейка", "Папка"],
        "Чай и кофе": ["Чай чёрный", "Чай зелёный", "Кофе молотый", "Какао"],
        "Хозтовары": ["Губка", "Мыло", "Пакеты", "Салфетки", "Перчатки"],
    }
    goods = ["Артикул;Товар;Категория"]
    articles = []
    number = 100
    for category, names in categories.items():
        for name in names:
            number += rng.randint(1, 9)
            goods.append(f"{number};{name};{category}")
            articles.append(number)
    sales = ["ID;Дата;Артикул;Количество;Цена"]
    start = dt.date(2026, 3, 1)
    for sale_id in range(1, 321):
        day = start + dt.timedelta(days=rng.randint(0, 30))
        sales.append(
            f"{sale_id};{day:%d.%m.%Y};{rng.choice(articles)};"
            f"{rng.randint(1, 12)};{rng.randint(20, 400)}"
        )
    return {"i03_1_goods.csv": goods, "i03_1_sales.csv": sales}


@_seed(302)
def _i03_2(rng: random.Random) -> dict[str, list[str]]:
    genres = ["Фантастика", "Детектив", "Приключения", "Поэзия", "Научно-популярное"]
    books = ["Шифр;Жанр;Год издания"]
    codes = []
    for i in range(1, 61):
        code = f"К-{i:03d}"
        codes.append(code)
        books.append(f"{code};{rng.choice(genres)};{rng.randint(1995, 2025)}")
    groups = ["Школьник", "Студент", "Взрослый", "Пенсионер"]
    branches = ["Северный", "Южный", "Центральный"]
    readers = ["Билет;Возрастная группа;Филиал"]
    tickets = []
    for i in range(1, 81):
        ticket = 5000 + i
        tickets.append(ticket)
        readers.append(f"{ticket};{rng.choice(groups)};{rng.choice(branches)}")
    loans = ["ID;Дата;Билет;Шифр;Операция"]
    start = dt.date(2026, 10, 1)
    for loan_id in range(1, 2001):
        day = start + dt.timedelta(days=rng.randint(0, 29))
        operation = rng.choice(["Выдача", "Выдача", "Возврат"])
        loans.append(
            f"{loan_id};{day:%d.%m.%Y};{rng.choice(tickets)};{rng.choice(codes)};{operation}"
        )
    return {
        "i03_2_books.csv": books,
        "i03_2_readers.csv": readers,
        "i03_2_loans.csv": loans,
    }


@_seed(303)
def _i03_3(rng: random.Random) -> dict[str, list[str]]:
    tariffs = [("Утро", 150), ("Стандарт", 220), ("Премиум", 340)]
    tariff_rows = ["Тариф;Цена за час"] + [f"{name};{price}" for name, price in tariffs]
    districts = ["Центр", "Заводской", "Лесной"]
    clients = ["Клиент;Тариф;Район"]
    ids = []
    for i in range(1, 51):
        client = f"C{i:02d}"
        ids.append(client)
        clients.append(f"{client};{rng.choice(tariffs)[0]};{rng.choice(districts)}")
    visits = ["ID;Дата;Клиент;Вход;Выход"]
    start = dt.date(2026, 11, 1)
    for visit_id in range(1, 451):
        day = start + dt.timedelta(days=rng.randint(0, 29))
        enter = rng.randint(7 * 60, 19 * 60)
        leave = enter + rng.randint(25, 200)
        visits.append(
            f"{visit_id};{day:%d.%m.%Y};{rng.choice(ids)};"
            f"{enter // 60:02d}:{enter % 60:02d};{leave // 60:02d}:{leave % 60:02d}"
        )
    return {
        "i03_3_tariffs.csv": tariff_rows,
        "i03_3_clients.csv": clients,
        "i03_3_visits.csv": visits,
    }


# ── №9: строки чисел (вместо электронной таблицы — CSV) ──────────────────────


def _rows(rng: random.Random, count: int, width: int, low: int, high: int) -> list[str]:
    return [";".join(str(rng.randint(low, high)) for _ in range(width)) for _ in range(count)]


@_seed(901)
def _i09_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i09_1.csv": _rows(rng, 1500, 4, 1, 100)}


@_seed(902)
def _i09_2(rng: random.Random) -> dict[str, list[str]]:
    return {"i09_2.csv": _rows(rng, 2000, 6, 1, 60)}


@_seed(903)
def _i09_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i09_3.csv": _rows(rng, 2500, 7, 20, 70)}


# ── №10: текст (вместо документа Word — обычный текстовый файл) ──────────────

_FILLER = [
    "утром",
    "вечером",
    "тихо",
    "город",
    "река",
    "поле",
    "небо",
    "ветер",
    "солнце",
    "дождь",
    "снег",
    "облако",
    "дорога",
    "старый",
    "новый",
    "большой",
    "маленький",
    "быстро",
    "медленно",
    "шумный",
    "дети",
    "взрослые",
    "шли",
    "бежали",
    "смотрели",
    "слушали",
    "говорили",
    "думали",
    "видели",
    "долго",
    "коротко",
    "рядом",
    "далеко",
    "около",
    "через",
    "над",
    "под",
    "возле",
    "после",
    "перед",
    "мимо",
    "берег",
    "камень",
    "трава",
    "цветы",
    "птицы",
    "голос",
    "песня",
    "окно",
    "дверь",
    "крыша",
    "улица",
    "площадь",
    "сад",
    "огород",
    "машина",
    "поезд",
    "автобус",
    "письмо",
    "книга",
    "друг",
    "сосед",
    "учитель",
    "мастер",
    "рыбак",
    "охотник",
    "художник",
    "светлый",
    "тёмный",
    "тёплый",
    "холодный",
]
_CONNECT = ("и", "а", "но", "в", "на", "у", "по", "за", "к", "с")


def _text(rng: random.Random, special: list[str], banned: str, sentences: int) -> list[str]:
    filler = [w for w in _FILLER if banned not in w]
    lines = []
    paragraph: list[str] = []
    for _ in range(sentences):
        words = []
        for _ in range(rng.randint(5, 12)):
            roll = rng.random()
            if roll < 0.12:
                words.append(rng.choice(special))
            elif roll < 0.3:
                words.append(rng.choice(_CONNECT))
            else:
                words.append(rng.choice(filler))
        if rng.random() < 0.3:
            words[0] = rng.choice(special)
        words[0] = words[0][0].upper() + words[0][1:]
        if len(words) > 6 and rng.random() < 0.4:
            words[3] += ","
        paragraph.append(" ".join(words) + rng.choice([".", ".", ".", "!", "?"]))
        if len(paragraph) >= rng.randint(4, 8):
            lines.append(" ".join(paragraph))
            paragraph = []
    if paragraph:
        lines.append(" ".join(paragraph))
    return lines


@_seed(1001)
def _i10_1(rng: random.Random) -> dict[str, list[str]]:
    special = ["мост", "мост", "мост", "мосты", "мостик", "мостовая", "помост", "мостом"]
    return {"i10_1.txt": _text(rng, special, "мост", 400)}


@_seed(1002)
def _i10_2(rng: random.Random) -> dict[str, list[str]]:
    special = ["лес", "лесной", "лесник", "лестница", "перелесок", "полесье", "лесу", "лесам"]
    return {"i10_2.txt": _text(rng, special, "лес", 450)}


@_seed(1003)
def _i10_3(rng: random.Random) -> dict[str, list[str]]:
    special = [
        "вода",
        "водный",
        "водопровод",
        "подводный",
        "заводь",
        "провод",
        "наводнение",
        "водяной",
        "развод",
        "водой",
    ]
    return {"i10_3.txt": _text(rng, special, "вод", 500)}


# ── №17: последовательности ────────────────────────────────────────────────


@_seed(1701)
def _i17_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i17_1.txt": [str(rng.randint(-10000, 10000)) for _ in range(6000)]}


@_seed(1702)
def _i17_2(rng: random.Random) -> dict[str, list[str]]:
    numbers = []
    for _ in range(8000):
        value = rng.randint(10, 99) if rng.random() < 0.45 else rng.randint(100, 9999)
        numbers.append(str(value if rng.random() < 0.7 else -value))
    return {"i17_2.txt": numbers}


@_seed(1703)
def _i17_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i17_3.txt": [str(rng.randint(-5000, 5000)) for _ in range(9000)]}


# ── №18: Робот (вместо электронной таблицы — CSV, «#» — стена) ──────────────


def _grid(rng: random.Random, size: int, wall_share: float) -> list[str]:
    rows = []
    for r in range(size):
        cells = []
        for c in range(size):
            corner = (r, c) in {(0, 0), (size - 1, size - 1)}
            if not corner and rng.random() < wall_share:
                cells.append("#")
            else:
                cells.append(str(rng.randint(1, 99)))
        rows.append(";".join(cells))
    return rows


@_seed(1801)
def _i18_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i18_1.csv": _grid(rng, 12, 0.0)}


@_seed(1802)
def _i18_2(rng: random.Random) -> dict[str, list[str]]:
    return {"i18_2.csv": _grid(rng, 15, 0.15)}


@_seed(1803)
def _i18_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i18_3.csv": _grid(rng, 20, 0.2)}


# ── №22: процессы (вместо электронной таблицы — CSV) ─────────────────────────


def _processes(rng: random.Random, count: int, max_deps: int) -> list[str]:
    rows = ["ID;Время;Зависимости"]
    for pid in range(1, count + 1):
        earlier = list(range(1, pid))
        k = rng.randint(0, min(max_deps, len(earlier)))
        deps = sorted(rng.sample(earlier, k)) if k else []
        rows.append(f"{pid};{rng.randint(2, 15)};{','.join(map(str, deps)) or '0'}")
    return rows


@_seed(2201)
def _i22_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i22_1.csv": _processes(rng, 12, 2)}


@_seed(2202)
def _i22_2(rng: random.Random) -> dict[str, list[str]]:
    return {"i22_2.csv": _processes(rng, 20, 2)}


@_seed(2203)
def _i22_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i22_3.csv": _processes(rng, 25, 3)}


# ── №24: длинные строки ─────────────────────────────────────────────────────


def _string(rng: random.Random, letters: str, weights: list[int], length: int) -> list[str]:
    return ["".join(rng.choices(letters, weights=weights, k=length))]


@_seed(2401)
def _i24_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i24_1.txt": _string(rng, "XYZW", [4, 4, 1, 1], 40000)}


@_seed(2402)
def _i24_2(rng: random.Random) -> dict[str, list[str]]:
    return {"i24_2.txt": _string(rng, "QRSTZ", [3, 3, 3, 3, 1], 60000)}


@_seed(2403)
def _i24_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i24_3.txt": _string(rng, "ABC", [41, 30, 29], 80000)}


# ── №25: параметры перебора (границы и маска) ───────────────────────────────


@_seed(2501)
def _i25_1(rng: random.Random) -> dict[str, list[str]]:
    return {"i25_1.txt": ["400000 450000"]}


@_seed(2502)
def _i25_2(rng: random.Random) -> dict[str, list[str]]:
    return {"i25_2.txt": ["250000 270000"]}


@_seed(2503)
def _i25_3(rng: random.Random) -> dict[str, list[str]]:
    return {"i25_3.txt": ["4?8*21 1307 100000000"]}


# ── №26: данные и сортировка ────────────────────────────────────────────────


@_seed(2601)
def _i26_1(rng: random.Random) -> dict[str, list[str]]:
    masses = [rng.randint(5, 900) for _ in range(1000)]
    return {"i26_1.txt": [f"20000 {len(masses)}", *map(str, masses)]}


@_seed(2602)
def _i26_2(rng: random.Random) -> dict[str, list[str]]:
    rows = []
    for _ in range(3000):
        start = rng.randint(0, 14 * 60)
        rows.append(f"{start} {start + rng.randint(15, 180)}")
    return {"i26_2.txt": [str(len(rows)), *rows]}


@_seed(2603)
def _i26_3(rng: random.Random) -> dict[str, list[str]]:
    rows = []
    for _ in range(5000):
        duration = rng.randint(1, 60)
        rows.append(f"{duration} {rng.randint(duration, 60000)}")
    return {"i26_3.txt": [str(len(rows)), *rows]}


# ── №27: кластеры точек с целыми координатами ───────────────────────────────


def _cluster(rng: random.Random, cx: int, cy: int, radius: int, count: int) -> set[tuple]:
    points: set[tuple[int, int]] = set()
    while len(points) < count:
        dx = rng.randint(-radius, radius)
        dy = rng.randint(-radius, radius)
        if dx * dx + dy * dy <= radius * radius:
            points.add((cx + dx, cy + dy))
    return points


def _points_file(rng: random.Random, groups: list[set[tuple]]) -> list[str]:
    points = [p for group in groups for p in sorted(group)]
    rng.shuffle(points)
    return [f"{x} {y}" for x, y in points]


@_seed(2701)
def _i27_1(rng: random.Random) -> dict[str, list[str]]:
    groups = [_cluster(rng, 120, 340, 25, 300), _cluster(rng, 610, 95, 25, 280)]
    return {"i27_1.txt": _points_file(rng, groups)}


@_seed(2702)
def _i27_2(rng: random.Random) -> dict[str, list[str]]:
    groups = [
        _cluster(rng, -400, 150, 30, 420),
        _cluster(rng, 200, -350, 25, 260),
        _cluster(rng, 500, 400, 28, 350),
    ]
    return {"i27_2.txt": _points_file(rng, groups)}


@_seed(2703)
def _i27_3(rng: random.Random) -> dict[str, list[str]]:
    groups = [
        _cluster(rng, 0, 0, 30, 450),
        _cluster(rng, 700, 50, 26, 330),
        _cluster(rng, 300, 600, 28, 390),
        _cluster(rng, -500, 450, 24, 280),
    ]
    anomalies: set[tuple[int, int]] = set()
    while len(anomalies) < 25:
        point = (rng.randint(-900, 1100), rng.randint(-400, 1000))
        if all(abs(point[0] - gx) + abs(point[1] - gy) > 150 for gx, gy in _CENTERS_27_3):
            anomalies.add(point)
    return {"i27_3.txt": _points_file(rng, [*groups, anomalies])}


_CENTERS_27_3 = [(0, 0), (700, 50), (300, 600), (-500, 450)]


# ── сборка ──────────────────────────────────────────────────────────────────


def build_all() -> dict[str, bytes]:
    """Содержимое всех файлов: имя → байты (UTF-8, переводы строк LF)."""
    result: dict[str, bytes] = {}
    for seed, generator in sorted(_GENERATORS.items()):
        for name, lines in generator(random.Random(seed)).items():
            assert name not in result, name
            result[name] = ("\n".join(lines) + "\n").encode("utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=FILES_DIR, help="папка для файлов")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in build_all().items():
        # Двоичный режим: в Windows переводы строк тоже останутся LF.
        (args.out / name).write_bytes(content)


if __name__ == "__main__":
    main()
