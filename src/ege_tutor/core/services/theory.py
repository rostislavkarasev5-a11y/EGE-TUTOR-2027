"""Теория по навыкам из content/theory/ (ADR-0022).

Файл `<код навыка>.md`: в начале между строками `---` — заголовок YAML (навык, название,
источник, версия, примеры), дальше — текст теории. Тексты пишет Claude своими словами, ответы
примеров проверяют тесты tests/content/test_theory.py (поле `check` у примера).
Ошибка в любом файле останавливает загрузку: лучше сразу узнать, чем показать неверную теорию.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ege_tutor.core.domain import Catalog, Theory, TheoryExample

THEORY_DIR = "theory"
THEORY_SOURCE = "AI_GENERATED"
EXAMPLE_FIELDS = ("title", "statement", "solution", "answer")


class TheoryError(Exception):
    """Ошибка в файле теории."""


@dataclass(frozen=True)
class TheoryLibrary:
    by_skill: dict[str, Theory] = field(default_factory=dict)

    def get(self, skill_code: str) -> Theory | None:
        return self.by_skill.get(skill_code)

    def __contains__(self, skill_code: object) -> bool:
        return skill_code in self.by_skill

    def __len__(self) -> int:
        return len(self.by_skill)


def split_front_matter(text: str) -> tuple[dict, str]:
    """Заголовок YAML между первыми строками `---` и текст после него."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("файл должен начинаться со строки ---")
    try:
        end = next(n for n in range(1, len(lines)) if lines[n].strip() == "---")
    except StopIteration:
        raise ValueError("нет закрывающей строки --- после заголовка") from None
    header = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(header, dict):
        raise ValueError("заголовок должен быть словарём YAML")
    return header, "\n".join(lines[end + 1 :]).strip()


def _example(raw: object, n: int) -> TheoryExample:
    if not isinstance(raw, dict):
        raise ValueError(f"пример {n}: ожидается словарь")
    values = {}
    for name in EXAMPLE_FIELDS:
        value = raw.get(name)
        if value is None or not str(value).strip():
            raise ValueError(f"пример {n}: нет поля {name}")
        values[name] = str(value).strip()
    return TheoryExample(**values)


def parse_theory(text: str, skill_codes: set[str]) -> Theory:
    header, body = split_front_matter(text)
    skill = str(header.get("skill", ""))
    if skill not in skill_codes:
        raise ValueError(f"навыка «{skill}» нет в каталоге")
    if header.get("source") != THEORY_SOURCE:
        raise ValueError(f"source должен быть {THEORY_SOURCE}: теорию пишет ИИ (Claude)")
    version = header.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("version — целое число от 1")
    title = str(header.get("title", "")).strip()
    if not title:
        raise ValueError("нет title")
    if not body:
        raise ValueError("нет текста теории")
    examples = header.get("examples") or []
    if not isinstance(examples, list) or not examples:
        raise ValueError("нужен хотя бы один пример")
    return Theory(
        skill_code=skill,
        title=title,
        text=body,
        examples=tuple(_example(raw, n) for n, raw in enumerate(examples, 1)),
        source=THEORY_SOURCE,
        version=version,
    )


def load_theory(content_dir: Path, catalog: Catalog) -> TheoryLibrary:
    folder = content_dir / THEORY_DIR
    if not folder.is_dir():
        return TheoryLibrary()
    skill_codes = {skill.code for topic in catalog.topics for skill in topic.skills}
    by_skill: dict[str, Theory] = {}
    for path in sorted(folder.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        try:
            theory = parse_theory(path.read_text(encoding="utf-8"), skill_codes)
        except (ValueError, yaml.YAMLError) as e:
            raise TheoryError(f"ошибка в {path.name}: {e}") from e
        if path.stem != theory.skill_code:
            raise TheoryError(
                f"{path.name}: имя файла должно совпадать с навыком {theory.skill_code}"
            )
        by_skill[theory.skill_code] = theory
    return TheoryLibrary(by_skill)
