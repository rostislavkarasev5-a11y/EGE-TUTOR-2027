"""Импорт сохранённой страницы Решу ЕГЭ (ADR-0021).

Страницы здесь придуманы для тестов: разметка повторяет устройство страницы
результатов, а задачи написаны заново (это не задачи с сайта).
"""

from pathlib import Path

import pytest

from ege_tutor.core.domain import AnswerType, Subject, TaskSource, VerificationStatus
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import RemoteFileError
from ege_tutor.core.services.reshu_ege import (
    SubsectionMap,
    formula_text,
    load_subsection_maps,
    parse_results_page,
)
from ege_tutor.remote.sdamgia import allowed_url

REPO_ROOT = Path(__file__).resolve().parents[2]
SHY = "\xad"


def _row(pos: int, pid: str, item: int, title: str, answer: str) -> str:
    return (
        f'<tr class="res_row"><td><a href="#prob{pos}">{pos}</a></td>'
        f'<td><a href="/problem?id={pid}" target="_blank">{pid}</a></td>'
        f'<td title="{title}">{item}</td><td>1</td><td>{answer}</td></tr>'
    )


def _problem(pos: int, pid: str, item: int, statement: str, solution: str, right: str) -> str:
    tail = f"<br>Ваш ответ: 1. Пра{SHY}виль{SHY}ный ответ: {right}<br>" if right else ""
    return (
        f'<div style="margin-bottom:25px" class="not_right">'
        f'<a name="prob{pos}"></a><a href="#" title="Наверх">&uarr;</a>'
        f"<b>За{SHY}да{SHY}ние {pos} № {pid} тип {item}</b>"
        f"<span>(решено неверно или не решено)</span><br>"
        f'<div align="justify" class="pbody">{statement}</div><br>'
        f'<br><b>Решение.</b><br><div align="justify" class="pbody">{solution}</div>'
        f'{tail}<div class="expand"><div id="comments{pid}" style="display:none"></div></div>'
        f"</div>"
    )


def _page(title: str, rows: list[str], problems: list[str]) -> str:
    return (
        f"<html><head><title>{title}</title></head><body>"
        '<div class="Header-SubjectName">Предмет</div>'
        '<div class="test_results"><table class="res_table">'
        "<tr><th>№</th><th>№</th><th>Тип</th><th>Ваш ответ</th><th>Правильный ответ</th></tr>"
        + "".join(rows)
        + "</table></div><div>"
        + "".join(problems)
        + "</div></body></html>"
    )


MATH_TITLE = "ЕГЭ–2026, математика профильная: задания, ответы, решения"
MATH_PAGE = _page(
    MATH_TITLE,
    [
        _row(1, "900001", 1, "Задания 1. Планиметрия. Трапеция", "7"),
        _row(2, "900002", 8, "Задания 8. Вычисления. Действия со степенями", "0,5"),
        _row(3, "900003", 14, "Задания 14. Уравнения. Логарифмические уравнения", ""),
    ],
    [
        _problem(
            1,
            "900001",
            1,
            '<p class="left_margin"><img src="/get_file?id=111" style="float:right">'
            '<p class="left_margin">Ос&shy;но&shy;ва&shy;ния тра&shy;пе&shy;ции '
            "равны&#8239;4 и 10. "
            "Най&shy;ди&shy;те сред&shy;нюю линию.",
            "Средняя линия равна полусумме оснований: "
            '<img class="tex" src="https://ege.sdamgia.ru/formula/svg/a.svg" '
            'alt="дробь: чис&shy;ли&shy;тель: 4 плюс 10, '
            'зна&shy;ме&shy;на&shy;тель: 2 конец дроби =7"'
            "/>.<p>Ответ: 7.",
            "7",
        ),
        _problem(
            2,
            "900002",
            8,
            "<p>Най&shy;ди&shy;те зна&shy;че&shy;ние вы&shy;ра&shy;же&shy;ния "
            '<img class="tex" src="https://ege.sdamgia.ru/formula/svg/b.svg" '
            'alt="2 в сте&shy;пе&shy;ни минус 1"/>.',
            "<p>Ответ: 0,5.",
            "0,5",
        ),
        _problem(
            3,
            "900003",
            14,
            "<p>а) Решите уравнение log<sub>2</sub>(x+1)=3. б) Укажите корни на отрезке [0; 10].",
            '<p>Получаем x+1=8.<img src="/get_file?id=222"><p>Ответ: а) 7; б) 7.',
            "",
        ),
    ],
)

INFORMATICS_PAGE = _page(
    "ЕГЭ–2026, информатика: задания, ответы, решения",
    [_row(1, "800001", 25, "Задания 25. Обработка целочисленной информации. Маска числа", "")],
    [
        _problem(
            1,
            "800001",
            25,
            '<p>Найдите два числа из файла <a href="/get_file?id=333">25.txt</a>.',
            "<p>Перебираем числа.",
            "12 3456",
        )
    ],
)


class FakeRemote:
    """Скачивание без сети: отдаёт маленькую картинку, один адрес — с ошибкой."""

    def __init__(self, broken: set[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self.broken = broken

    def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        self.calls.append(url)
        if url in self.broken:
            raise RemoteFileError(f"не удалось скачать {url}")
        if url.endswith("333"):
            return b"1 2 3\n", "text/plain"
        return b"\x89PNG fake", "image/png"


# ── разбор страницы ─────────────────────────────────────────────────────────


def test_parse_math_results_page():
    page = parse_results_page(MATH_PAGE)
    assert page.subject == Subject.MATH_PROFILE
    first, second, third = page.problems
    assert (first.problem_id, first.exam_item, first.answer) == ("900001", 1, "7")
    assert first.statement == "Основания трапеции равны 4 и 10. Найдите среднюю линию."
    assert first.subsection == "Планиметрия. Трапеция"
    assert first.files == ["https://math-ege.sdamgia.ru/get_file?id=111"]
    assert "(4 плюс 10)/(2)" in first.solution
    assert second.answer == "0,5"
    assert "2 в степени минус 1" in second.statement
    # Часть 2: в таблице ответа нет — он берётся из строки «Ответ:» в решении.
    assert third.answer == "а) 7; б) 7"
    assert third.files == ["https://math-ege.sdamgia.ru/get_file?id=222"]


def test_variant_page_without_answers_is_explained():
    page = (
        f"<html><head><title>{MATH_TITLE}</title></head><body>"
        '<div class="prob_maindiv" id="maindiv1"><div class="pbody">Условие</div></div>'
        "</body></html>"
    )
    with pytest.raises(Exception, match="страница самого варианта"):
        parse_results_page(page)


@pytest.mark.parametrize(
    ("title", "message"),
    [
        ("ЕГЭ–2026, математика базовая: задания", "базовой математики"),
        ("ЕГЭ–2026, физика: задания", "какой это предмет"),
    ],
)
def test_other_subjects_are_rejected(title, message):
    page = MATH_PAGE.replace(MATH_TITLE, title)
    with pytest.raises(Exception, match=message):
        parse_results_page(page)


def test_formula_text_unwraps_nested_fractions():
    alt = (
        "дробь: числитель: 1, знаменатель: "
        "дробь: числитель: 2, знаменатель: 3 конец дроби конец дроби"
    )
    assert formula_text(alt) == "(1)/((2)/(3))"


# ── подразделы → навыки ─────────────────────────────────────────────────────


def test_subsection_lookup():
    maps = load_subsection_maps(REPO_ROOT / "content")
    math = maps[Subject.MATH_PROFILE]
    assert math.skills(1, "Планиметрия. Трапеция") == ("M01.quadrilaterals",)
    # Регистр, «ё» и уточнение после названия не мешают.
    assert math.skills(8, "Вычисления. Действия со степенями") == ("M07.powers_roots",)
    assert math.skills(9, "Производная. ПЕРВООБРАЗНАЯ функции") == ("M08.antiderivative",)
    assert math.skills(1, "Совсем новый подраздел") == ("M01.triangles",)
    assert math.skills(1, None) == ("M01.triangles",)
    assert SubsectionMap({}).skills(1, "что угодно") == ()


def test_subsection_table_matches_catalog(tutor):
    maps = load_subsection_maps(REPO_ROOT / "content")
    for subject, mapping in maps.items():
        known = tutor._skill_items(subject)
        spec = tutor.catalog.specs[subject]
        assert mapping.all_skills() <= set(known), subject
        for item, table in mapping.items.items():
            assert spec.item(item) is not None, (subject, item)
            assert table.get("default"), (subject, item)
            for skills in table.values():
                for code in skills:
                    assert not known[code] or item in known[code], (subject, item, code)
    # Каждый номер обоих экзаменов покрыт таблицей.
    for subject, spec in tutor.catalog.specs.items():
        assert {i.number for i in spec.items} == set(maps[subject].items), subject


# ── страница → задачи в базе ────────────────────────────────────────────────


def test_convert_and_import_math_page(tutor, write_file):
    tutor.remote_files = FakeRemote()
    page = write_file("variant.html", MATH_PAGE)
    conversion = tutor.convert_reshu_page(page)
    assert conversion.problems == 3
    assert conversion.files_downloaded == 2
    assert conversion.file_errors == []

    report = tutor.preview_import(conversion.task_file)
    assert report.errors == []
    result = tutor.import_tasks(conversion.task_file)
    assert result.batch.added_count == 3

    tasks = {t.source_ref: t for t in tutor.tasks(Subject.MATH_PROFILE)}
    first = tasks["Решу ЕГЭ, задача №900001, подраздел «Планиметрия. Трапеция»"]
    assert first.source == TaskSource.USER_MATERIAL
    assert first.source_version == "Решу ЕГЭ 2027"
    assert first.verification_status == VerificationStatus.REVIEWED
    assert first.answer == "7"
    assert first.skills == ("M01.quadrilaterals",)
    assert [a.file_name for a in first.assets] == ["reshu_111.png"]
    assert tutor.asset_path(first.assets[0]).read_bytes() == b"\x89PNG fake"
    assert first.can_practice

    third = next(t for t in tasks.values() if t.exam_item == 14)
    assert third.answer_type == AnswerType.EXTENDED
    assert third.skills == ("M13.exp_log_equations", "M13.root_selection")


def test_broken_picture_does_not_stop_import(tutor, write_file):
    tutor.remote_files = FakeRemote(broken={"https://math-ege.sdamgia.ru/get_file?id=111"})
    conversion = tutor.convert_reshu_page(write_file("variant.html", MATH_PAGE))
    assert len(conversion.file_errors) == 1
    assert "900001" in conversion.file_errors[0]
    assert tutor.import_tasks(conversion.task_file).batch.added_count == 3


def test_informatics_page_with_file_and_two_numbers(tutor, write_file):
    tutor.remote_files = FakeRemote()
    conversion = tutor.convert_reshu_page(write_file("inf.html", INFORMATICS_PAGE))
    assert conversion.subject == Subject.INFORMATICS
    tutor.import_tasks(conversion.task_file)
    (task,) = tutor.tasks(Subject.INFORMATICS)
    assert task.answer_type == AnswerType.SEQUENCE
    assert task.answer == "12 3456"
    assert task.skills == ("I25.divisors_masks",)
    assert [a.file_name for a in task.assets] == ["reshu_333.txt"]


def test_import_twice_finds_duplicates(tutor, write_file):
    tutor.remote_files = FakeRemote()
    tutor.import_tasks(tutor.convert_reshu_page(write_file("a/variant.html", MATH_PAGE)).task_file)
    again = tutor.convert_reshu_page(write_file("b/variant.html", MATH_PAGE))
    report = tutor.preview_import(again.task_file)
    assert not report.accepted
    assert all("уже есть в базе" in e.message for e in report.errors)


def test_not_a_reshu_page(tutor, write_file):
    with pytest.raises(AppError, match="не найдено задач"):
        tutor.convert_reshu_page(write_file("x.html", "<html><body>Привет</body></html>"))


def test_create_uses_sdamgia_adapter(write_file, fixed_clock):
    from ege_tutor.core.app import TutorApp

    app = TutorApp.create(clock=fixed_clock)
    try:
        assert app.remote_files.__class__.__name__ == "SdamgiaFiles"
    finally:
        app.close()


# ── адаптер скачивания ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://math-ege.sdamgia.ru/get_file?id=1", True),
        ("https://sdamgia.ru/x.png", True),
        ("http://math-ege.sdamgia.ru/get_file?id=1", False),
        ("https://evil.example/get_file?id=1", False),
        ("https://sdamgia.ru.evil.example/x", False),
        ("https://user@math-ege.sdamgia.ru/x", False),
        ("https://math-ege.sdamgia.ru:8080/x", False),
        ("https://notsdamgia.ru/x", False),
        ("file:///etc/passwd", False),
    ],
)
def test_only_sdamgia_https_urls(url, ok):
    assert allowed_url(url) is ok
