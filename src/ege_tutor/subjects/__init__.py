"""Предметные тьюторы: правила и проверка ответов по каждому предмету."""

from typing import Protocol

from ege_tutor.core.domain import AnswerCheck, AnswerType, Subject


class SubjectTutor(Protocol):
    def check_answer(self, answer_type: AnswerType, expected: str, given: str) -> AnswerCheck:
        """Проверить краткий ответ. Развёрнутые ответы — Phase 8."""
        ...


def tutor_for(subject: Subject) -> SubjectTutor:
    from ege_tutor.subjects.informatics.tutor import InformaticsTutor
    from ege_tutor.subjects.math.tutor import MathTutor

    return MathTutor() if subject == Subject.MATH_PROFILE else InformaticsTutor()


__all__ = ["SubjectTutor", "tutor_for"]
