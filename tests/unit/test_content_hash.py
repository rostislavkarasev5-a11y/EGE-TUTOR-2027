"""Поиск дублей: хэш не зависит от регистра и лишних пробелов."""

from hypothesis import given
from hypothesis import strategies as st

from ege_tutor.core.domain import Subject
from ege_tutor.core.services.content_import import content_hash

words = st.lists(st.text(alphabet="абвгдxyz0123456789=+", min_size=1), min_size=1, max_size=8)


@given(words, st.sampled_from([" ", "  ", "\n", "\t "]))
def test_hash_ignores_whitespace_and_case(parts, sep):
    plain = " ".join(parts)
    noisy = f"  {sep.join(parts).upper()} {sep}"
    assert content_hash(Subject.MATH_PROFILE, 6, plain) == content_hash(
        Subject.MATH_PROFILE, 6, noisy
    )


@given(words)
def test_hash_depends_on_subject_and_item(parts):
    text = " ".join(parts)
    hashes = {
        content_hash(Subject.MATH_PROFILE, 6, text),
        content_hash(Subject.MATH_PROFILE, 7, text),
        content_hash(Subject.INFORMATICS, 6, text),
    }
    assert len(hashes) == 3
