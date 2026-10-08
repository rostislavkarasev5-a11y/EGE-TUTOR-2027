"""Mastery, ошибки и повторения (Phase 4, ADR-0006, ADR-0015).

Как это связано с попытками:
- начало попытки → предсказание модели в prediction_log;
- конец попытки → факт в prediction_log, ошибки (правилами), пересчёт навыков задачи,
  снимок за сегодня, пересчёт паттернов ошибок этих навыков.

Mastery — производная величина: всё здесь можно пересчитать по сырым попыткам.
"""

import dataclasses
import datetime as dt
import math
from collections.abc import Iterable
from dataclasses import dataclass

from ege_tutor.config import MasteryConfig
from ege_tutor.core.domain import (
    Attempt,
    AttemptStatus,
    Catalog,
    MasteryAggregate,
    MasteryRecord,
    MasterySnapshot,
    Mistake,
    MistakeCategory,
    MistakePattern,
    ReviewItem,
    ReviewReason,
    SkillMastery,
    Subject,
    Task,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository, RepositoryError
from ege_tutor.core.services.mastery_model import MasteryModel, MasteryModelV0, SkillState
from ege_tutor.core.services.mistakes import (
    build_patterns,
    classify,
    is_mistake,
    pattern_priority,
)


@dataclass(frozen=True)
class Calibration:
    """Насколько предсказания модели совпали с фактом (чем меньше, тем лучше)."""

    count: int
    brier: float | None
    log_loss: float | None
    mean_predicted: float | None
    mean_actual: float | None


@dataclass(frozen=True)
class SkillInfo:
    code: str
    title: str
    subject: Subject
    topic_code: str
    exam_items: tuple[int, ...]


class MasteryService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        config: MasteryConfig,
        catalog: Catalog,
        model: MasteryModel | None = None,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._config = config
        self.model: MasteryModel = model or MasteryModelV0(config)
        self.skills: dict[str, SkillInfo] = {
            skill.code: SkillInfo(
                skill.code,
                skill.title,
                topic.subject,
                topic.code,
                skill.exam_items or topic.exam_items,
            )
            for topic in catalog.topics
            for skill in topic.skills
        }
        self._catalog = catalog

    # ── состояние навыков ───────────────────────────────────────────────────

    def _record(self, code: str, state: SkillState, now: dt.datetime) -> MasteryRecord:
        return MasteryRecord(
            skill_code=code,
            model_version=self.model.version,
            value_raw=state.value_raw,
            confidence=state.confidence,
            stability_days=state.stability_days,
            attempts=state.attempts,
            last_practiced_at=state.last_practiced_at,
            next_review_on=self.model.next_review(state),
            updated_at=now,
        )

    def _as_state(self, record: MasteryRecord) -> SkillState:
        return SkillState(
            value_raw=record.value_raw,
            confidence=record.confidence,
            stability_days=record.stability_days,
            attempts=record.attempts,
            last_practiced_at=record.last_practiced_at,
        )

    def _view(self, record: MasteryRecord, now: dt.datetime) -> SkillMastery:
        return SkillMastery(
            skill_code=record.skill_code,
            model_version=record.model_version,
            value=self.model.forgotten(self._as_state(record), now),
            value_raw=record.value_raw,
            confidence=record.confidence,
            stability_days=record.stability_days,
            attempts=record.attempts,
            last_practiced_at=record.last_practiced_at,
            next_review_on=record.next_review_on,
            as_of=now.date(),
        )

    def recalculate(self, skill_codes: Iterable[str]) -> list[SkillMastery]:
        """Пересчитать навыки по всей их истории; снимок — только за сегодня."""
        now = self._clock.now()
        records, snapshots = [], []
        for code in dict.fromkeys(skill_codes):
            state = self.model.state(self._repo.skill_history(code))
            if state is None:
                continue
            record = self._record(code, state, now)
            records.append(record)
            snapshots.append(
                MasterySnapshot(
                    snapshot_date=now.date(),
                    skill_code=code,
                    model_version=record.model_version,
                    value=self.model.forgotten(state, now),
                    value_raw=record.value_raw,
                    confidence=record.confidence,
                )
            )
        self._repo.save_mastery(records, snapshots)
        return [self._view(r, now) for r in records]

    def recalculate_all(self) -> int:
        """Пересчитать все изученные навыки и все паттерны ошибок по истории."""
        codes = self._repo.practiced_skills()
        self.recalculate(codes)
        for code in codes:
            self._rebuild_patterns(code)
        return len(codes)

    def skill_masteries(self, subject: Subject | None = None) -> list[SkillMastery]:
        now = self._clock.now()
        found = [self._view(r, now) for r in self._repo.list_mastery()]
        if subject is not None:
            found = [
                m
                for m in found
                if m.skill_code in self.skills and self.skills[m.skill_code].subject == subject
            ]
        return found

    def _aggregate(
        self, key: str, title: str, subject: Subject, codes: list[str], known: dict
    ) -> MasteryAggregate:
        studied = [known[c] for c in codes if c in known]
        if not studied:
            return MasteryAggregate(key, title, subject, None, 0.0, 0, len(codes))
        weights = [max(m.confidence, 1e-6) for m in studied]
        value = sum(w * m.value for w, m in zip(weights, studied, strict=True)) / sum(weights)
        # неизученные навыки тянут тему вниз: «один из пяти» — ещё не освоенная тема
        value *= len(studied) / len(codes)
        confidence = sum(m.confidence for m in studied) / len(codes)
        return MasteryAggregate(key, title, subject, value, confidence, len(studied), len(codes))

    def by_topic(self, subject: Subject) -> list[MasteryAggregate]:
        known = {m.skill_code: m for m in self.skill_masteries(subject)}
        return [
            self._aggregate(t.code, t.title, subject, [s.code for s in t.skills], known)
            for t in self._catalog.topics_of(subject)
            if t.skills
        ]

    def by_exam_item(self, subject: Subject) -> list[MasteryAggregate]:
        known = {m.skill_code: m for m in self.skill_masteries(subject)}
        spec = self._catalog.specs.get(subject)
        if spec is None:
            return []
        result = []
        for item in spec.items:
            codes = [
                s.code
                for s in self.skills.values()
                if s.subject == subject and item.number in s.exam_items
            ]
            if codes:
                result.append(self._aggregate(str(item.number), item.title, subject, codes, known))
        return result

    # ── предсказания ────────────────────────────────────────────────────────

    def predict(self, task: Task) -> float | None:
        """Вероятность решить задачу самостоятельно: среднее M её навыков (неизученный — 0)."""
        if not task.skills:
            return None
        now = self._clock.now()
        known = {
            r.skill_code: self.model.forgotten(self._as_state(r), now)
            for r in self._repo.list_mastery(task.skills)
        }
        return sum(known.get(code, 0.0) for code in task.skills) / len(task.skills)

    def on_attempt_started(self, attempt: Attempt, task: Task) -> None:
        predicted = self.predict(task)
        if predicted is None:
            return
        self._repo.add_prediction(
            attempt_id=attempt.id,
            task_id=task.id,
            model_version=self.model.version,
            predicted=min(1.0, max(0.0, predicted)),
            created_at=self._clock.now(),
        )

    def calibration(self) -> Calibration:
        resolved = [p for p in self._repo.list_predictions(limit=100_000) if p.outcome is not None]
        if not resolved:
            return Calibration(0, None, None, None, None)
        eps = 1e-6
        brier = sum((p.predicted - p.outcome) ** 2 for p in resolved) / len(resolved)
        log_loss = -sum(
            math.log(min(1 - eps, max(eps, p.predicted)))
            if p.outcome
            else math.log(min(1 - eps, max(eps, 1 - p.predicted)))
            for p in resolved
        ) / len(resolved)
        return Calibration(
            count=len(resolved),
            brier=round(brier, 4),
            log_loss=round(log_loss, 4),
            mean_predicted=round(sum(p.predicted for p in resolved) / len(resolved), 4),
            mean_actual=round(sum(p.outcome or 0 for p in resolved) / len(resolved), 4),
        )

    # ── конец попытки ───────────────────────────────────────────────────────

    def on_attempt_finished(self, attempt: Attempt, task: Task) -> list[Mistake]:
        """Записать факт, ошибки и пересчитать навыки задачи. Брошенные попытки не считаются."""
        if attempt.status not in (AttemptStatus.ANSWERED, AttemptStatus.GAVE_UP):
            return []
        now = self._clock.now()
        self._repo.resolve_prediction(attempt.id, 1 if attempt.independent else 0, now)
        mistakes: list[Mistake] = []
        if is_mistake(attempt):
            runs = self._repo.list_code_runs(task.id, attempt.id, limit=1)
            draft = classify(attempt, task, runs[0] if runs else None)
            mistakes = self._repo.add_mistakes(
                attempt_id=attempt.id,
                task_id=task.id,
                skill_codes=list(task.skills) or [None],
                draft=draft,
                created_at=now,
            )
        self.recalculate(task.skills)
        for code in task.skills:
            self._rebuild_patterns(code)
        return mistakes

    # ── ошибки и паттерны ───────────────────────────────────────────────────

    def _rebuild_patterns(self, skill_code: str) -> list[MistakePattern]:
        mistakes = self._repo.list_mistakes(skill_code=skill_code, limit=100_000)
        attempts = [a for a, _ in self._repo.skill_history(skill_code)]
        patterns = build_patterns(
            skill_code, mistakes, attempts, self._config.mistakes, self._clock.now()
        )
        self._repo.save_patterns(skill_code, patterns)
        return patterns

    def mistakes(self, skill_code: str | None = None, limit: int = 50) -> list[Mistake]:
        return self._repo.list_mistakes(skill_code=skill_code, limit=limit)

    def attempt_mistakes(self, attempt_id: int) -> list[Mistake]:
        return self._repo.list_mistakes(attempt_id=attempt_id)

    def reclassify(self, mistake_id: int, category: MistakeCategory) -> Mistake:
        """Пользователь уточнил, что пошло не так. Исходная запись остаётся в истории."""
        current = self._repo.get_mistake(mistake_id)
        if current is None:
            raise AppError(f"ошибка №{mistake_id} не найдена")
        try:
            updated = self._repo.reclassify_mistake(
                mistake_id, category, "уточнено пользователем", self._clock.now()
            )
        except RepositoryError as e:
            raise AppError(str(e)) from e
        if updated.skill_code:
            self._rebuild_patterns(updated.skill_code)
        return updated

    def patterns(self, open_only: bool = True) -> list[MistakePattern]:
        """Паттерны с приоритетом на сегодня: свежесть убывает со временем."""
        now = self._clock.now()
        found = [
            p
            if p.closed_at is not None
            else dataclasses.replace(
                p,
                priority=pattern_priority(
                    p.category, p.occurrences, p.last_at, self._config.mistakes, now
                ),
            )
            for p in self._repo.list_patterns(open_only)
        ]
        return sorted(found, key=lambda p: (-p.priority, p.skill_code))

    # ── очередь повторений ──────────────────────────────────────────────────

    def review_queue(self, subject: Subject | None = None) -> list[ReviewItem]:
        """Сначала навыки, которым пора на повторение, потом открытые паттерны ошибок."""
        masteries = {m.skill_code: m for m in self.skill_masteries(subject)}
        items: list[ReviewItem] = []
        due = sorted(
            (m for m in masteries.values() if m.review_due and m.skill_code in self.skills),
            key=lambda m: (m.value, m.skill_code),
        )
        for m in due:
            info = self.skills[m.skill_code]
            items.append(
                ReviewItem(
                    m.skill_code,
                    info.title,
                    info.subject,
                    ReviewReason.FORGETTING,
                    m.value,
                    m.next_review_on,
                )
            )
        listed = {i.skill_code for i in items}
        for p in self.patterns(open_only=True):
            info = self.skills.get(p.skill_code)
            if info is None or (subject is not None and info.subject != subject):
                continue
            if p.skill_code in listed:
                continue
            listed.add(p.skill_code)
            m = masteries.get(p.skill_code)
            items.append(
                ReviewItem(
                    p.skill_code,
                    info.title,
                    info.subject,
                    ReviewReason.MISTAKES,
                    m.value if m else None,
                    None,
                    p.category,
                    p.priority,
                )
            )
        return items
