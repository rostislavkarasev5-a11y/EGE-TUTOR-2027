"""Теория по навыкам (ADR-0022): файлы читаются, ответы примеров сходятся с проверкой.

У каждого примера с числовым ответом есть поле `check` — выражение, которое SymPy вычисляет
отдельно от текста решения. Ответ примера должен совпасть с ним точно.
"""

import pytest
import sympy as sp
import yaml

from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.core.services.theory import THEORY_DIR, load_theory, split_front_matter
from tests.conftest import REPO_ROOT

CONTENT = REPO_ROOT / "content"
FILES = sorted(p for p in (CONTENT / THEORY_DIR).glob("*.md") if p.name.upper() != "README.MD")
EXAMPLES_PER_SKILL = 7
FORBIDDEN = ("ФИПИ", "fipi.ru", "sdamgia", "Решу ЕГЭ")


def _number(text: str) -> sp.Rational | None:
    try:
        return sp.Rational(text.strip().replace(",", ".").replace("−", "-"))
    except (TypeError, ValueError):
        return None


def test_all_theory_loads():
    library = load_theory(CONTENT, load_catalog(CONTENT))
    assert len(library) == len(FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_examples_are_checked(path):
    header, _ = split_front_matter(path.read_text(encoding="utf-8"))
    examples = header["examples"]
    assert len(examples) == EXAMPLES_PER_SKILL, "в теории 7 примеров (ADR-0022)"
    for n, ex in enumerate(examples, 1):
        expected = _number(str(ex["answer"]))
        if expected is None:
            assert "check" not in ex, f"пример {n}: check бывает только у числового ответа"
            continue
        assert "check" in ex, f"пример {n}: у числового ответа нужно поле check"
        value = sp.nsimplify(sp.sympify(str(ex["check"]), rational=True))
        assert value == expected, f"пример {n}: ответ {ex['answer']}, а проверка даёт {value}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_theory_is_own_text(path):
    text = path.read_text(encoding="utf-8")
    header, _ = split_front_matter(text)
    assert header["source"] == "AI_GENERATED"
    for word in FORBIDDEN:
        assert word not in text, f"в теории не должно быть ссылок на чужие материалы: {word}"


def test_yaml_is_safe():
    for path in FILES:
        header, _ = split_front_matter(path.read_text(encoding="utf-8"))
        assert yaml.safe_dump(header)
