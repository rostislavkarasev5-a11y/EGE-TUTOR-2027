"""Критерии самопроверки заданий части 2 (Phase 8, ADR-0022, п. 5).

Критерии ФИПИ пересказаны своими словами в content/exam_specs/2027/criteria/*.yaml. Ученик
выбирает ОДИН уровень — самый высокий, которому его решение соответствует полностью; балл
уровня и есть балл за задание. Если файла критериев нет, используется общий список уровней
«N из M баллов».
"""

from dataclasses import dataclass

from ege_tutor.core.domain.subject import Subject


@dataclass(frozen=True)
class CriterionLevel:
    points: int
    text: str


@dataclass(frozen=True)
class Part2Criteria:
    """Уровни оценки одного задания части 2: от большего балла к меньшему."""

    subject: Subject
    exam_item: int
    max_points: int
    levels: tuple[CriterionLevel, ...]
    tips: tuple[str, ...] = ()
    source: str = ""
    note: str = ""  # пометка «пересказ, сверить с официальными критериями»
    generic: bool = False  # общий список уровней: файла критериев для задания нет

    def level(self, points: int) -> CriterionLevel | None:
        return next((lv for lv in self.levels if lv.points == points), None)


def generic_criteria(subject: Subject, exam_item: int, max_points: int) -> Part2Criteria:
    """Запасной вариант без файла критериев: уровни max..0 с текстом «N из M баллов»."""
    return Part2Criteria(
        subject=subject,
        exam_item=exam_item,
        max_points=max_points,
        levels=tuple(
            CriterionLevel(p, f"{p} из {max_points} баллов") for p in range(max_points, -1, -1)
        ),
        note="Критериев для этого задания пока нет: оцени решение сам, сравнив с эталоном.",
        generic=True,
    )
