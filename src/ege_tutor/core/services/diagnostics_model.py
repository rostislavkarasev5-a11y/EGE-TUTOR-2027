"""Модель адаптивной диагностики diag-v0 (ADR-0016).

Уровень ученика по номеру k: θₖ = g + δₖ, где g — общий уровень по предмету,
δₖ — отклонение номера. Prior: g ~ N(0, σ_g²), δₖ ~ N(0, σ_δ²). Всё считается точно на сетках,
поэтому результат объясним и воспроизводим: тот же список ответов — та же оценка.

    P(верно | θ, d) = guess + (1 − guess) · σ(θ − (d − 3))

Модель — чистые функции без базы: posterior каждый раз пересчитывается из ответов.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import NormalDist

from ege_tutor.config import DiagnosticsModel
from ege_tutor.core.domain import DiagnosticObservation, Forecast


@dataclass(frozen=True)
class ItemSpec:
    """Номер экзамена так, как его видит модель."""

    number: int
    max_points: int


def _grid(limit: float, step: float) -> tuple[float, ...]:
    count = round(limit / step)
    return tuple(i * step for i in range(-count, count + 1))


def _normal_weights(grid: Sequence[float], sd: float) -> tuple[float, ...]:
    raw = [math.exp(-0.5 * (x / sd) ** 2) for x in grid]
    total = sum(raw)
    return tuple(w / total for w in raw)


@dataclass
class _ItemPosterior:
    """Данные одного номера при каждом значении g: Z(g), E[p | g], E[p² | g]."""

    weights: list[list[float]]  # [g][δ]: prior(δ) · правдоподобие ответов номера
    z: list[float]
    m1: list[float]
    m2: list[float]


class DiagnosticModelV0:
    def __init__(self, config: DiagnosticsModel) -> None:
        self.config = config
        self.version = config.model_version
        self.abilities = _grid(config.ability_grid_limit, config.grid_step)
        self.offsets = _grid(config.offset_grid_limit, config.grid_step)
        self._prior_g = _normal_weights(self.abilities, config.ability_prior_sd)
        self._prior_d = _normal_weights(self.offsets, config.item_offset_sd)
        self._prior_item = self._item_posterior(())
        prior_mean = sum(w * m for w, m in zip(self._prior_g, self._prior_item.m1, strict=True))
        prior_m2 = sum(w * m for w, m in zip(self._prior_g, self._prior_item.m2, strict=True))
        self.prior_item_variance = max(prior_m2 - prior_mean**2, 1e-12)

    # ── вероятность и правдоподобие ──

    def probability(self, theta: float, difficulty: int) -> float:
        """P(решу задачу сложности difficulty) при уровне theta."""
        guess = self.config.guess
        return guess + (1 - guess) / (1 + math.exp(-(theta - (difficulty - 3))))

    def likelihood(self, theta: float, obs: DiagnosticObservation) -> float:
        p = self.probability(theta, obs.difficulty)
        if not obs.correct:
            return 1 - p
        return p**self.config.slow_evidence if obs.slow else p

    # ── posterior номера ──

    def _summarize(self, weights: list[list[float]]) -> _ItemPosterior:
        reference = self.config.reference_difficulty
        z, m1, m2 = [], [], []
        for g, row in zip(self.abilities, weights, strict=True):
            total = sum(row)
            ps = [self.probability(g + d, reference) for d in self.offsets]
            z.append(total)
            m1.append(sum(w * p for w, p in zip(row, ps, strict=True)) / total)
            m2.append(sum(w * p * p for w, p in zip(row, ps, strict=True)) / total)
        return _ItemPosterior(weights, z, m1, m2)

    def _item_posterior(self, observations: Iterable[DiagnosticObservation]) -> _ItemPosterior:
        weights = [list(self._prior_d) for _ in self.abilities]
        for obs in observations:
            weights = self._multiplied(weights, obs)
        return self._summarize(weights)

    def _multiplied(
        self, weights: list[list[float]], obs: DiagnosticObservation
    ) -> list[list[float]]:
        return [
            [w * self.likelihood(g + d, obs) for w, d in zip(row, self.offsets, strict=True)]
            for g, row in zip(self.abilities, weights, strict=True)
        ]

    def _with(self, item: _ItemPosterior, obs: DiagnosticObservation) -> _ItemPosterior:
        """Posterior номера после ещё одного ответа."""
        return self._summarize(self._multiplied(item.weights, obs))

    def state(
        self, items: Sequence[ItemSpec], observations: Iterable[DiagnosticObservation]
    ) -> "DiagnosticModelState":
        by_item: dict[int, list[DiagnosticObservation]] = {item.number: [] for item in items}
        for obs in observations:
            if obs.exam_item in by_item:
                by_item[obs.exam_item].append(obs)
        posteriors = {
            number: self._item_posterior(obs) if obs else self._prior_item
            for number, obs in by_item.items()
        }
        return DiagnosticModelState(self, tuple(items), posteriors)


def _normalized(values: Sequence[float]) -> list[float]:
    total = sum(values)
    return [v / total for v in values]


class DiagnosticModelState:
    """Posterior по всем номерам предмета и прогноз первичного балла."""

    def __init__(
        self,
        model: DiagnosticModelV0,
        items: tuple[ItemSpec, ...],
        posteriors: dict[int, _ItemPosterior],
    ) -> None:
        self.model = model
        self.items = items
        self._posteriors = posteriors
        self._post_g = self._ability_posterior(posteriors)

    def _ability_posterior(self, posteriors: dict[int, _ItemPosterior]) -> list[float]:
        # логарифмы, чтобы произведение многих маленьких Z не ушло в ноль
        logs = [math.log(w) for w in self.model._prior_g]
        for post in posteriors.values():
            logs = [acc + math.log(z) for acc, z in zip(logs, post.z, strict=True)]
        top = max(logs)
        return _normalized([math.exp(v - top) for v in logs])

    # ── оценки ──

    def item_estimate(self, number: int) -> tuple[float, float]:
        """P(решу задачу средней сложности номера) и уверенность в оценке."""
        post = self._posteriors[number]
        mean = sum(w * m for w, m in zip(self._post_g, post.m1, strict=True))
        second = sum(w * m for w, m in zip(self._post_g, post.m2, strict=True))
        variance = max(second - mean**2, 0.0)
        confidence = 1 - math.sqrt(variance / self.model.prior_item_variance)
        return mean, min(1.0, max(0.0, confidence))

    def _moments(
        self, post_g: Sequence[float], posteriors: dict[int, _ItemPosterior]
    ) -> tuple[float, float]:
        """Среднее и дисперсия первичного балла: E[S] и Var(S) с учётом общего уровня g."""
        mean = second = 0.0
        for gi, weight in enumerate(post_g):
            cond_mean = cond_var = 0.0
            for item in self.items:
                post = posteriors[item.number]
                cond_mean += item.max_points * post.m1[gi]
                cond_var += item.max_points**2 * max(post.m2[gi] - post.m1[gi] ** 2, 0.0)
            mean += weight * cond_mean
            second += weight * (cond_var + cond_mean**2)
        return mean, max(second - mean**2, 0.0)

    @property
    def variance(self) -> float:
        return self._moments(self._post_g, self._posteriors)[1]

    def forecast(self, interval: float) -> Forecast:
        mean, variance = self._moments(self._post_g, self._posteriors)
        z = NormalDist().inv_cdf(0.5 + interval / 2)
        half = z * math.sqrt(variance)
        top = sum(item.max_points for item in self.items)
        return Forecast(
            mean=mean,
            low=max(0.0, mean - half),
            high=min(float(top), mean + half),
            max_points=top,
            interval=interval,
        )

    # ── выбор задачи ──

    def expected_gain(self, number: int, difficulty: int) -> float:
        """На сколько в среднем уменьшится Var(S), если дать задачу этого номера и сложности."""
        model = self.model
        post = self._posteriors[number]
        # P(верно | g) для этой задачи — по posterior δ номера при каждом g
        p_correct_g = []
        for g, row, z in zip(model.abilities, post.weights, post.z, strict=True):
            p = sum(
                w * model.probability(g + d, difficulty)
                for w, d in zip(row, model.offsets, strict=True)
            )
            p_correct_g.append(p / z)
        p_correct = sum(w * p for w, p in zip(self._post_g, p_correct_g, strict=True))
        current = self._moments(self._post_g, self._posteriors)[1]
        expected = 0.0
        for correct, p_outcome in ((True, p_correct), (False, 1 - p_correct)):
            if p_outcome <= 0:
                continue
            obs = DiagnosticObservation(number, difficulty, correct=correct, slow=False)
            updated = model._with(post, obs)
            # новый posterior g: старый × Z_новый / Z_старый для этого номера
            post_g = _normalized(
                [w * zn / zo for w, zn, zo in zip(self._post_g, updated.z, post.z, strict=True)]
            )
            posteriors = self._posteriors | {number: updated}
            expected += p_outcome * self._moments(post_g, posteriors)[1]
        return current - expected
