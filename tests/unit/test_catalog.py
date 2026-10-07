"""Каталог: структура экзаменов, темы и навыки из content/."""

import dataclasses

import pytest

from ege_tutor.config import load_settings
from ege_tutor.core.domain import AnswerKind, Subject
from ege_tutor.core.services.catalog import CatalogError, load_catalog, validate_catalog


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_settings().content_dir)


def test_math_spec_matches_current_structure(catalog):
    spec = catalog.specs[Subject.MATH_PROFILE]
    assert spec.exam_year == 2027
    assert spec.status == "provisional"
    assert len(spec.items) == 19
    assert all(i.answer_kind == AnswerKind.SHORT for i in spec.items[:12])
    assert all(i.answer_kind == AnswerKind.EXTENDED for i in spec.items[12:])
    assert spec.max_primary_score == 32


def test_informatics_spec_matches_current_structure(catalog):
    spec = catalog.specs[Subject.INFORMATICS]
    assert len(spec.items) == 27
    assert all(i.answer_kind == AnswerKind.SHORT for i in spec.items)
    assert spec.max_primary_score == 29


def test_every_exam_item_is_covered_by_a_skill(catalog):
    for subject, spec in catalog.specs.items():
        covered = {n for t in catalog.topics_of(subject) for s in t.skills for n in s.exam_items}
        assert {i.number for i in spec.items} <= covered


def test_codes_are_unique_and_prefixed_by_topic(catalog):
    for topic in catalog.topics:
        for skill in topic.skills:
            assert skill.code.startswith(topic.code + ".")


def test_spec_source_is_explicit(catalog):
    for spec in catalog.specs.values():
        assert "ФИПИ" in spec.source


def _replace_skill(catalog, **changes):
    topic = catalog.topics[0]
    skill = dataclasses.replace(topic.skills[0], **changes)
    new_topic = dataclasses.replace(topic, skills=(skill, *topic.skills[1:]))
    return dataclasses.replace(catalog, topics=(new_topic, *catalog.topics[1:]))


def test_validation_rejects_unknown_prerequisite(catalog):
    with pytest.raises(CatalogError, match="предпосылки"):
        validate_catalog(_replace_skill(catalog, requires=("NOPE.skill",)))


def test_validation_rejects_unknown_exam_item(catalog):
    with pytest.raises(CatalogError, match="нет заданий"):
        validate_catalog(_replace_skill(catalog, exam_items=(99,)))


def test_validation_rejects_duplicate_skill_code(catalog):
    second = catalog.topics[1].skills[0].code
    with pytest.raises(CatalogError, match="повторяется"):
        validate_catalog(_replace_skill(catalog, code=second))


def test_validation_rejects_uncovered_item(catalog):
    topics = tuple(t for t in catalog.topics if t.code != "M19")
    with pytest.raises(CatalogError, match="не покрыты"):
        validate_catalog(dataclasses.replace(catalog, topics=topics))


def test_missing_content_dir_is_reported(tmp_path):
    with pytest.raises(CatalogError, match="не найден"):
        load_catalog(tmp_path)


def test_time_norms_fill_the_whole_exam(catalog):
    for spec in catalog.specs.values():
        assert sum(i.time_norm_seconds for i in spec.items) == spec.duration_minutes * 60
        assert "не ФИПИ" in spec.time_norm_source
