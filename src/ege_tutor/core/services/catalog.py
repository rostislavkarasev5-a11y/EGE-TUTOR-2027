"""Загрузка каталога из content/: структура экзаменов, темы и навыки.

Каталог проверяется целиком при загрузке: уникальность кодов, существование номеров
заданий и навыков-предпосылок, покрытие каждого номера экзамена хотя бы одним навыком.
"""

from pathlib import Path

import yaml

from ege_tutor.core.domain import (
    AnswerKind,
    Catalog,
    ExamSpec,
    ExamSpecItem,
    Skill,
    Subject,
    Topic,
)

EXAM_YEAR = 2027
SPEC_FILES = {
    Subject.MATH_PROFILE: "math_profile.yaml",
    Subject.INFORMATICS: "informatics.yaml",
}
TOPIC_FILES = {
    Subject.MATH_PROFILE: "math/topics.yaml",
    Subject.INFORMATICS: "informatics/topics.yaml",
}


class CatalogError(Exception):
    """Ошибка в файлах каталога."""


def _read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise CatalogError(f"не найден файл каталога: {path}") from e
    except yaml.YAMLError as e:
        raise CatalogError(f"ошибка YAML в {path.name}: {e}") from e
    if not isinstance(data, dict):
        raise CatalogError(f"{path.name}: ожидается словарь верхнего уровня")
    return data


def _load_spec(path: Path, subject: Subject) -> ExamSpec:
    data = _read_yaml(path)
    try:
        if Subject(data["subject"]) != subject:
            raise CatalogError(f"{path.name}: subject не совпадает с {subject}")
        items = tuple(
            ExamSpecItem(
                number=int(i["number"]),
                title=str(i["title"]),
                part=int(i["part"]),
                answer_kind=AnswerKind(i["answer_kind"]),
                max_points=int(i["max_points"]),
                time_norm_seconds=round(float(i["time_norm_minutes"]) * 60),
            )
            for i in data["items"]
        )
        spec = ExamSpec(
            subject=subject,
            exam_year=int(data["exam_year"]),
            status=str(data["status"]),
            source=str(data["source"]),
            duration_minutes=int(data["duration_minutes"]),
            items=items,
            time_norm_source=str(data["time_norm_source"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise CatalogError(f"{path.name}: неверная структура ({e})") from e
    numbers = [i.number for i in items]
    if numbers != list(range(1, len(numbers) + 1)):
        raise CatalogError(f"{path.name}: номера заданий должны идти подряд с 1")
    if any(i.time_norm_seconds <= 0 for i in items):
        raise CatalogError(f"{path.name}: норматив времени должен быть положительным")
    return spec


def _load_topics(path: Path, subject: Subject) -> tuple[Topic, ...]:
    data = _read_yaml(path)
    try:
        if Subject(data["subject"]) != subject:
            raise CatalogError(f"{path.name}: subject не совпадает с {subject}")
        topics = []
        for t in data["topics"]:
            topic_items = tuple(int(n) for n in t.get("exam_items", []))
            skills = tuple(
                Skill(
                    code=str(s["code"]),
                    title=str(s["title"]),
                    exam_items=tuple(int(n) for n in s.get("exam_items", topic_items)),
                    requires=tuple(str(r) for r in s.get("requires", [])),
                )
                for s in t["skills"]
            )
            topics.append(Topic(str(t["code"]), subject, str(t["title"]), topic_items, skills))
    except (KeyError, TypeError, ValueError) as e:
        raise CatalogError(f"{path.name}: неверная структура ({e})") from e
    return tuple(topics)


def validate_catalog(catalog: Catalog) -> None:
    topic_codes = [t.code for t in catalog.topics]
    skill_codes = [s.code for t in catalog.topics for s in t.skills]
    for kind, codes in (("темы", topic_codes), ("навыка", skill_codes)):
        duplicates = {c for c in codes if codes.count(c) > 1}
        if duplicates:
            raise CatalogError(f"повторяется код {kind}: {', '.join(sorted(duplicates))}")
    all_skills = set(skill_codes)
    for subject, spec in catalog.specs.items():
        numbers = {i.number for i in spec.items}
        covered: set[int] = set()
        for topic in catalog.topics_of(subject):
            for skill in topic.skills:
                unknown = set(skill.exam_items) - numbers
                if unknown:
                    raise CatalogError(f"{skill.code}: нет заданий с номерами {sorted(unknown)}")
                missing = set(skill.requires) - all_skills
                if missing:
                    raise CatalogError(f"{skill.code}: неизвестные предпосылки {sorted(missing)}")
                covered.update(skill.exam_items)
        if numbers - covered:
            raise CatalogError(
                f"{subject}: задания {sorted(numbers - covered)} не покрыты ни одним навыком"
            )


def load_catalog(content_dir: Path) -> Catalog:
    specs = {
        subject: _load_spec(content_dir / "exam_specs" / str(EXAM_YEAR) / name, subject)
        for subject, name in SPEC_FILES.items()
    }
    topics = tuple(
        topic
        for subject, name in TOPIC_FILES.items()
        for topic in _load_topics(content_dir / name, subject)
    )
    catalog = Catalog(specs=specs, topics=topics)
    validate_catalog(catalog)
    return catalog
