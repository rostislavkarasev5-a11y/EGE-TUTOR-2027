"""Учебный блок по навыку — конечный автомат (архитектура, 5.3; ADR-0022).

ТЕОРИЯ → ПРИМЕРЫ → САМОСТОЯТЕЛЬНЫЕ → ПРОВЕРКА → РАЗБОР ОШИБОК → ЗАДАЧИ НА ОШИБКИ → ДОМАШКА → ГОТОВО

Шаг хранится в базе, поэтому блок можно прервать и продолжить. Шаги с задачами заканчиваются
сами, когда решено нужное число задач или задачи на навык закончились. Ошибка — попытка,
решённая неверно, сдача или решение с подсказкой. Если ошибок нет, разбор пропускается.
Попытки блока — обычные попытки (PRACTICE и HOMEWORK): mastery и ошибки считаются как всегда.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from ege_tutor.config import LearningConfig
from ege_tutor.core.domain import (
    STEP_ROLES,
    Attempt,
    AttemptMode,
    AttemptStatus,
    Catalog,
    Lesson,
    LessonCheck,
    LessonProgress,
    LessonStatus,
    LessonStep,
    LessonSuggestion,
    LessonTask,
    LessonTaskRole,
    Skill,
    SkillMastery,
    Subject,
    Task,
    Theory,
    TheoryExample,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository
from ege_tutor.core.services.theory import TheoryLibrary

FINISHED = (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP)
ROLE_MODES = {
    LessonTaskRole.INDEPENDENT: AttemptMode.PRACTICE,
    LessonTaskRole.MISTAKE: AttemptMode.PRACTICE,
    LessonTaskRole.HOMEWORK: AttemptMode.HOMEWORK,
}
# Шаги, которые ученик закрывает кнопкой («Прочитал», «Понял», «Дальше»).
CONFIRM_STEPS = frozenset({LessonStep.THEORY, LessonStep.EXAMPLES, LessonStep.CHECK})


@dataclass(frozen=True)
class LessonSources:
    """Что учебный блок берёт у других сервисов CORE."""

    tasks_for_skill: Callable[[str], list[Task]]  # проверенные задачи, реже решавшиеся — первыми
    start_attempt: Callable[[int, AttemptMode], Attempt]
    skill_masteries: Callable[[Subject], list[SkillMastery]]
    schedule_homework: Callable[[Lesson, int], None]
    today: Callable[[], dt.date]


class LessonService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        config: LearningConfig,
        catalog: Catalog,
        theory: TheoryLibrary,
        sources: LessonSources,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self.config = config
        self._catalog = catalog
        self._theory = theory
        self._src = sources
        self._skills: dict[str, tuple[Subject, Skill]] = {
            skill.code: (topic.subject, skill) for topic in catalog.topics for skill in topic.skills
        }

    # ── навыки и теория ─────────────────────────────────────────────────────

    def skill(self, skill_code: str) -> tuple[Subject, Skill]:
        found = self._skills.get(skill_code)
        if found is None:
            raise AppError(f"навыка «{skill_code}» нет в каталоге")
        return found

    def theory(self, skill_code: str) -> Theory | None:
        self.skill(skill_code)
        return self._theory.get(skill_code)

    def examples(self, skill_code: str) -> tuple[TheoryExample, ...]:
        theory = self.theory(skill_code)
        return theory.examples[: self.config.examples] if theory else ()

    def has_theory(self, skill_code: str) -> bool:
        return skill_code in self._theory

    # ── блоки ───────────────────────────────────────────────────────────────

    def lesson(self, lesson_id: int) -> Lesson:
        lesson = self._repo.get_lesson(lesson_id)
        if lesson is None:
            raise AppError(f"учебный блок №{lesson_id} не найден")
        return lesson

    def lessons(self, status: LessonStatus | None = None, limit: int = 50) -> list[Lesson]:
        return self._repo.list_lessons(status=status, limit=limit)

    def active(self, skill_code: str) -> Lesson | None:
        found = self._repo.list_lessons(skill_code, LessonStatus.ACTIVE, limit=1)
        return found[0] if found else None

    def start(self, skill_code: str) -> Lesson:
        """Начать блок по навыку или вернуть уже начатый."""
        subject, _ = self.skill(skill_code)
        current = self.active(skill_code)
        if current is not None:
            return current
        return self._repo.create_lesson(
            subject=subject, skill_code=skill_code, at=self._clock.now()
        )

    def abandon(self, lesson_id: int) -> Lesson:
        lesson = self._open(lesson_id)
        return self._repo.update_lesson(
            lesson.id, step=lesson.step, status=LessonStatus.ABANDONED, at=self._clock.now()
        )

    def lesson_of_attempt(self, attempt_id: int) -> int | None:
        return self._repo.lesson_of_attempt(attempt_id)

    def _open(self, lesson_id: int) -> Lesson:
        lesson = self.lesson(lesson_id)
        if lesson.status != LessonStatus.ACTIVE:
            raise AppError(f"учебный блок №{lesson_id} уже {lesson.status_name}")
        return lesson

    # ── попытки блока ───────────────────────────────────────────────────────

    def tasks(self, lesson_id: int) -> list[LessonTask]:
        return [
            LessonTask(
                attempt_id=attempt.id,
                task_id=attempt.task_id,
                role=role,
                finished=attempt.status in FINISHED,
                correct=attempt.correct,
                independent=attempt.independent,
                reviewed=reviewed,
            )
            for role, attempt, reviewed in self._repo.lesson_attempts(lesson_id)
        ]

    def check(self, lesson_id: int) -> LessonCheck:
        """Итог самостоятельных: доля верных без подсказок и попытки для разбора."""
        done = [
            t for t in self.tasks(lesson_id) if t.role == LessonTaskRole.INDEPENDENT and t.finished
        ]
        good = sum(1 for t in done if t.correct and t.independent)
        share = good / len(done) if done else None
        return LessonCheck(
            total=len(done),
            good=good,
            share=share,
            passed=share is not None and share >= self.config.pass_share,
            problems=tuple(t.attempt_id for t in done if t.problem),
        )

    def target(self, lesson: Lesson, role: LessonTaskRole) -> int:
        """Сколько задач нужно решить на шаге по правилам (ADR-0022)."""
        cfg = self.config
        if role == LessonTaskRole.INDEPENDENT:
            return cfg.independent_tasks
        if role == LessonTaskRole.MISTAKE:
            return cfg.mistake_tasks * len(lesson.mistake_skills)
        return min(
            cfg.homework_max,
            cfg.homework_base + cfg.homework_per_mistake * len(lesson.mistake_skills),
        )

    def _role_skills(self, lesson: Lesson, role: LessonTaskRole) -> list[str]:
        if role == LessonTaskRole.INDEPENDENT:
            return [lesson.skill_code]
        if role == LessonTaskRole.MISTAKE:
            return list(lesson.mistake_skills)
        return list(dict.fromkeys([lesson.skill_code, *lesson.mistake_skills]))

    def _candidates(
        self, lesson: Lesson, role: LessonTaskRole, tasks: list[LessonTask]
    ) -> list[Task]:
        """Задачи для шага по очереди навыков. Сначала — не решавшиеся в этом блоке."""
        finished_here = {t.task_id for t in tasks if t.role == role and t.finished}
        seen_in_lesson = {t.task_id for t in tasks}
        per_skill = []
        for skill_code in self._role_skills(lesson, role):
            pool = [t for t in self._src.tasks_for_skill(skill_code) if t.id not in finished_here]
            fresh = [t for t in pool if t.id not in seen_in_lesson]
            per_skill.append(fresh + [t for t in pool if t.id in seen_in_lesson])
        ordered: list[Task] = []
        used: set[int] = set()
        for rank in range(max((len(p) for p in per_skill), default=0)):
            for pool in per_skill:
                if rank < len(pool) and pool[rank].id not in used:
                    used.add(pool[rank].id)
                    ordered.append(pool[rank])
        return ordered

    def _open_attempt(self, lesson_id: int) -> Attempt | None:
        return next(
            (
                attempt
                for _, attempt, _ in self._repo.lesson_attempts(lesson_id)
                if attempt.status == AttemptStatus.IN_PROGRESS
            ),
            None,
        )

    # ── переходы ────────────────────────────────────────────────────────────

    def _move(self, lesson: Lesson, step: LessonStep, **changes) -> Lesson:
        status = LessonStatus.DONE if step == LessonStep.DONE else LessonStatus.ACTIVE
        moved = self._repo.update_lesson(
            lesson.id, step=step, status=status, at=self._clock.now(), **changes
        )
        if step == LessonStep.HOMEWORK:
            target = self.target(moved, LessonTaskRole.HOMEWORK)
            available = len(self._candidates(moved, LessonTaskRole.HOMEWORK, []))
            if min(target, available) > 0:
                self._src.schedule_homework(moved, min(target, available))
        return moved

    def _to_homework(self, lesson: Lesson, mistake_skills: tuple[str, ...]) -> Lesson:
        due = self._src.today() + dt.timedelta(days=self.config.homework_due_days)
        return self._move(
            lesson, LessonStep.HOMEWORK, mistake_skills=mistake_skills, homework_due=due
        )

    def _after_check(self, lesson: Lesson) -> Lesson:
        result = self.check(lesson.id)
        if not result.problems:
            return self._to_homework(lesson, ())
        tasks = {t.attempt_id: t for t in self.tasks(lesson.id)}
        skills = [lesson.skill_code]
        for attempt_id in result.problems:
            task = self._repo.get_task(tasks[attempt_id].task_id)
            if task is not None:
                skills.extend(s for s in task.skills if s in self._skills)
        return self._move(
            lesson, LessonStep.MISTAKE_REVIEW, mistake_skills=tuple(dict.fromkeys(skills))
        )

    def _settle(self, lesson: Lesson) -> Lesson:
        """Закрыть шаги, которые уже выполнены (задачи решены или закончились)."""
        while lesson.status == LessonStatus.ACTIVE:
            role = STEP_ROLES.get(lesson.step)
            if role is not None:
                tasks = self.tasks(lesson.id)
                if self._open_attempt(lesson.id) is not None:
                    return lesson
                done = sum(1 for t in tasks if t.role == role and t.finished)
                if done < self.target(lesson, role) and self._candidates(lesson, role, tasks):
                    return lesson
                following = {
                    LessonTaskRole.INDEPENDENT: LessonStep.CHECK,
                    LessonTaskRole.MISTAKE: LessonStep.HOMEWORK,
                    LessonTaskRole.HOMEWORK: LessonStep.DONE,
                }[role]
                if following == LessonStep.HOMEWORK:
                    lesson = self._to_homework(lesson, lesson.mistake_skills)
                else:
                    lesson = self._move(lesson, following)
            elif lesson.step == LessonStep.MISTAKE_REVIEW:
                problems = set(self.check(lesson.id).problems)
                left = [
                    t for t in self.tasks(lesson.id) if t.attempt_id in problems and not t.reviewed
                ]
                if left:
                    return lesson
                lesson = self._move(lesson, LessonStep.MISTAKE_TASKS)
            else:
                return lesson
        return lesson

    def confirm(self, lesson_id: int) -> Lesson:
        """Ученик закрыл шаг: «Прочитал» (теория), «Понял» (примеры), «Дальше» (проверка)."""
        lesson = self._settle(self._open(lesson_id))
        if lesson.step not in CONFIRM_STEPS:
            raise AppError(f"на шаге «{lesson.step_name}» кнопки «дальше» нет")
        if lesson.step == LessonStep.THEORY:
            lesson = self._move(lesson, LessonStep.EXAMPLES)
        elif lesson.step == LessonStep.EXAMPLES:
            lesson = self._move(lesson, LessonStep.INDEPENDENT)
        else:
            lesson = self._after_check(lesson)
        return self._settle(lesson)

    def mark_reviewed(self, lesson_id: int, attempt_id: int) -> Lesson:
        """Ошибка разобрана: ученик посмотрел решение и выбрал причину."""
        lesson = self._settle(self._open(lesson_id))
        if lesson.step != LessonStep.MISTAKE_REVIEW:
            raise AppError("сейчас не шаг «разбор ошибок»")
        if attempt_id not in self.check(lesson.id).problems:
            raise AppError(f"попытка №{attempt_id} не из ошибок этого блока")
        self._repo.mark_lesson_attempt_reviewed(attempt_id, self._clock.now())
        return self._settle(lesson)

    def progress(self, lesson_id: int) -> LessonProgress:
        lesson = self.lesson(lesson_id)
        if lesson.status == LessonStatus.ACTIVE:
            lesson = self._settle(lesson)
        role = STEP_ROLES.get(lesson.step)
        open_attempt = self._open_attempt(lesson.id)
        if role is None or lesson.status != LessonStatus.ACTIVE:
            return LessonProgress(lesson, 0, 0, False, None)
        tasks = self.tasks(lesson.id)
        done = sum(1 for t in tasks if t.role == role and t.finished)
        target = self.target(lesson, role)
        available = len(self._candidates(lesson, role, tasks))
        if open_attempt is not None:
            available = max(available, 1)
        return LessonProgress(
            lesson,
            done=done,
            target=target,
            short=done + available < target,
            open_attempt_id=open_attempt.id if open_attempt else None,
        )

    def next_attempt(self, lesson_id: int) -> Attempt | None:
        """Текущая задача шага: открытая попытка или новая. None — на этом шаге задач нет."""
        lesson = self._settle(self._open(lesson_id))
        role = STEP_ROLES.get(lesson.step)
        if role is None:
            return None
        current = self._open_attempt(lesson.id)
        if current is not None:
            return current
        candidates = self._candidates(lesson, role, self.tasks(lesson.id))
        if not candidates:
            return None
        attempt = self._src.start_attempt(candidates[0].id, ROLE_MODES[role])
        self._repo.add_lesson_attempt(lesson.id, attempt.id, role)
        return attempt

    def after_attempt(self, attempt_id: int) -> Lesson | None:
        """Попытка завершена: если она из блока, закрыть выполненный шаг."""
        lesson_id = self._repo.lesson_of_attempt(attempt_id)
        if lesson_id is None:
            return None
        lesson = self.lesson(lesson_id)
        return self._settle(lesson) if lesson.status == LessonStatus.ACTIVE else lesson

    # ── предложение для плана на день ───────────────────────────────────────

    def _left_on_step(self, lesson: Lesson) -> tuple[int, bool]:
        """Сколько задач осталось на ближайшем шаге с задачами и впереди ли чтение."""
        reading = lesson.step in (LessonStep.THEORY, LessonStep.EXAMPLES)
        role = STEP_ROLES.get(lesson.step) or (LessonTaskRole.INDEPENDENT if reading else None)
        if role is None:
            return 0, reading
        tasks = self.tasks(lesson.id)
        done = sum(1 for t in tasks if t.role == role and t.finished)
        available = len(self._candidates(lesson, role, tasks))
        return max(0, min(self.target(lesson, role) - done, available)), reading

    def suggestion(self, subject: Subject) -> LessonSuggestion | None:
        """Блок для плана: начатый (кроме домашки — она отдельным пунктом) или новый.

        Новый — по навыку с самым низким освоением, по которому блок ещё не проходили и
        есть задачи. Неизученные навыки идут первыми, среди них — с теорией.
        """
        for lesson in self._repo.list_lessons(status=LessonStatus.ACTIVE, limit=200):
            if lesson.subject != subject or lesson.step == LessonStep.HOMEWORK:
                continue
            left, reading = self._left_on_step(lesson)
            if left == 0 and not reading and lesson.step != LessonStep.MISTAKE_REVIEW:
                continue
            _, skill = self.skill(lesson.skill_code)
            return LessonSuggestion(
                subject,
                lesson.skill_code,
                lesson,
                f"учебный блок «{skill.title}»: следующий шаг — {lesson.step_name}",
                left,
                self.config.theory_minutes if reading else 0,
            )
        passed = {lesson.skill_code for lesson in self._repo.list_lessons(limit=10_000)}
        known = {m.skill_code: m.value for m in self._src.skill_masteries(subject)}
        rows = []
        for code in sorted(self._catalog.skill_codes(subject)):
            if code in passed:
                continue
            count = min(len(self._src.tasks_for_skill(code)), self.config.independent_tasks)
            if count == 0:
                continue
            value = known.get(code)
            rows.append(
                (
                    (value is not None, value or 0.0, code not in self._theory, code),
                    code,
                    value,
                    count,
                )
            )
        if not rows:
            return None
        _, code, value, count = min(rows)
        _, skill = self.skill(code)
        studied = f"освоение {value:.2f}" if value is not None else "ещё не изучали"
        return LessonSuggestion(
            subject,
            code,
            None,
            f"новая тема «{skill.title}»: {studied}",
            count,
            self.config.theory_minutes,
        )
