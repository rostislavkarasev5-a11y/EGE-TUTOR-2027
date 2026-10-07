"""Загрузка и проверка конфигурации из папки config/ (ADR-0005).

Конфигурация — три TOML-файла: app.toml, mastery.toml, diagnostics.toml.
Каждый проверяется моделью Pydantic; опечатка в имени ключа — ошибка, а не тихое игнорирование.
"""

import datetime as dt
import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ege_tutor.core.domain import Subject, VerificationStatus

CONFIG_DIR_ENV = "EGE_TUTOR_CONFIG_DIR"

Factor = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveWeight = Annotated[float, Field(gt=0.0)]


class ConfigError(Exception):
    """Конфигурация не найдена или содержит ошибку."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── app.toml ────────────────────────────────────────────────────────────────


class AppSection(_Strict):
    name: str
    data_dir: Path


class ExamDateConfig(_Strict):
    """Дата экзамена. До официального расписания — TBD без даты."""

    status: Literal["TBD", "OFFICIAL"]
    date: dt.date | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _date_matches_status(self) -> Self:
        if self.status == "TBD" and self.date is not None:
            raise ValueError("при status = 'TBD' дата не задаётся")
        if self.status == "OFFICIAL" and (self.date is None or not self.source):
            raise ValueError("при status = 'OFFICIAL' нужны date и source")
        return self


class AIConfig(_Strict):
    enabled: bool


SandboxBackend = Literal["docker", "wsl2"]


class SandboxConfig(_Strict):
    backend: SandboxBackend
    fallback_backend: SandboxBackend | None = None
    time_limit_seconds: PositiveWeight
    memory_limit_mb: Annotated[int, Field(gt=0)]
    network_enabled: bool


class AppConfig(_Strict):
    app: AppSection
    exams: dict[Subject, ExamDateConfig]
    ai: AIConfig
    sandbox: SandboxConfig

    @model_validator(mode="after")
    def _all_subjects_present(self) -> Self:
        missing = set(Subject) - set(self.exams)
        if missing:
            raise ValueError(f"нет настроек экзамена для: {', '.join(sorted(missing))}")
        return self


# ── mastery.toml ────────────────────────────────────────────────────────────


class IndependenceFactors(_Strict):
    level_0: Factor
    level_1: Factor
    level_2: Factor
    level_3: Factor
    level_4: Factor

    def for_hint_level(self, level: int) -> float:
        return getattr(self, f"level_{level}")


class TimeFactors(_Strict):
    within_norm: Factor
    up_to_double: Factor
    over_double: Factor


class RepeatFactors(_Strict):
    first: Factor
    second: Factor
    third_or_later: Factor


class DifficultyWeights(_Strict):
    d1: PositiveWeight
    d2: PositiveWeight
    d3: PositiveWeight
    d4: PositiveWeight
    d5: PositiveWeight


class ModeWeights(_Strict):
    practice: PositiveWeight
    homework: PositiveWeight
    review: PositiveWeight
    control: PositiveWeight
    diagnostic: PositiveWeight
    mock: PositiveWeight
    exam: PositiveWeight


class ForgettingConfig(_Strict):
    initial_stability_days: PositiveWeight
    review_threshold: Factor


class MasteryConfig(_Strict):
    """Коэффициенты Mastery v0 (ADR-0006).

    Множители свидетельства e — в диапазоне 0..1, поэтому e = произведение тоже в 0..1.
    Сложность и режим — это веса w, они на e не умножаются.
    """

    model_version: str
    independence: IndependenceFactors
    time_factor: TimeFactors
    repeat_factor: RepeatFactors
    difficulty_weight: DifficultyWeights
    mode_weight: ModeWeights
    forgetting: ForgettingConfig


# ── diagnostics.toml ────────────────────────────────────────────────────────


class DiagnosticsBudget(_Strict):
    max_tasks_per_subject: Annotated[int, Field(gt=0)]
    max_minutes_per_subject: Annotated[int, Field(gt=0)]


class DiagnosticsStopping(_Strict):
    target_forecast_half_width: PositiveWeight
    min_information_gain: Annotated[float, Field(ge=0.0)]


class DiagnosticsRules(_Strict):
    # Диагностика всегда без подсказок и без ИИ: включить их через конфиг нельзя.
    hints_allowed: Literal[False]
    ai_allowed: Literal[False]
    allowed_verification_statuses: Annotated[list[VerificationStatus], Field(min_length=1)]


class DiagnosticsConfig(_Strict):
    budget: DiagnosticsBudget
    stopping: DiagnosticsStopping
    rules: DiagnosticsRules


# ── загрузка ────────────────────────────────────────────────────────────────


class Settings(_Strict):
    config_dir: Path
    app: AppConfig
    mastery: MasteryConfig
    diagnostics: DiagnosticsConfig


def default_config_dir() -> Path:
    """Папка config/ в корне репозитория (src/ege_tutor/config.py → ../../config)."""
    return Path(__file__).resolve().parents[2] / "config"


def _read_toml[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"не найден файл конфигурации: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"ошибка синтаксиса TOML в {path.name}: {e}") from e
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"ошибка в {path.name}:\n{e}") from e


def load_settings(config_dir: Path | None = None) -> Settings:
    """Загрузить и проверить всю конфигурацию.

    Порядок выбора папки: аргумент → переменная окружения EGE_TUTOR_CONFIG_DIR →
    папка config/ репозитория.
    """
    if config_dir is None:
        env = os.environ.get(CONFIG_DIR_ENV)
        config_dir = Path(env) if env else default_config_dir()
    return Settings(
        config_dir=config_dir,
        app=_read_toml(config_dir / "app.toml", AppConfig),
        mastery=_read_toml(config_dir / "mastery.toml", MasteryConfig),
        diagnostics=_read_toml(config_dir / "diagnostics.toml", DiagnosticsConfig),
    )
