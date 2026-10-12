"""Загрузка и проверка конфигурации из папки config/ (ADR-0005).

Конфигурация — четыре TOML-файла: app.toml, mastery.toml, diagnostics.toml, planner.toml.
Каждый проверяется моделью Pydantic; опечатка в имени ключа — ошибка, а не тихое игнорирование.
"""

import datetime as dt
import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ege_tutor.core.domain import MistakeCategory, Subject, VerificationStatus

CONFIG_DIR_ENV = "EGE_TUTOR_CONFIG_DIR"
DATA_DIR_ENV = "EGE_TUTOR_DATA_DIR"
# Настройки ИИ, которые владелец задаёт на сервере, не меняя файлы репозитория (ADR-0017).
AI_PROVIDER_ENV = "EGE_AI_PROVIDER"
AI_MODEL_ENV = "EGE_AI_MODEL"
AI_BUDGET_ENV = "EGE_AI_MONTHLY_BUDGET_RUB"

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


AIProvider = Literal["disabled", "yandex"]
NonNegative = Annotated[float, Field(ge=0.0)]


class AIConfig(_Strict):
    """ИИ-слой (ADR-0017). Ключи здесь не хранятся: только в переменных окружения сервера."""

    provider: AIProvider
    model: Annotated[str, Field(min_length=1)]
    base_url: Annotated[str, Field(pattern=r"^https://")]
    monthly_budget_rub: NonNegative
    price_input_per_1000_rub: NonNegative
    price_output_per_1000_rub: NonNegative
    max_output_tokens: Annotated[int, Field(gt=0, le=8000)]
    timeout_seconds: PositiveWeight
    temperature: Annotated[float, Field(ge=0.0, le=1.0)] = 0.3

    def cost_rub(self, input_tokens: int, output_tokens: int) -> float:
        """Стоимость вызова по ценам из конфига."""
        return (
            input_tokens * self.price_input_per_1000_rub
            + output_tokens * self.price_output_per_1000_rub
        ) / 1000


class SpeechConfig(_Strict):
    """Голос репетитора (Phase 6.5, ADR-0018): Yandex SpeechKit тем же ключом, что и ИИ.

    Голос работает, только когда включён ИИ: у них общий ключ и общий месячный лимит.
    """

    enabled: bool
    voice: Annotated[str, Field(min_length=1, max_length=40)]
    role: Annotated[str, Field(max_length=40)] = ""
    speed: Annotated[float, Field(ge=0.5, le=2.0)] = 1.0
    tts_url: Annotated[str, Field(pattern=r"^https://")]
    stt_url: Annotated[str, Field(pattern=r"^https://")]
    # Цены по прайсу Yandex Cloud, рубли с НДС. Озвучка (API v3) — за запрос; длинный текст
    # SpeechKit делит на части, поэтому CORE считает запрос на каждые chars_per_request символов.
    price_tts_per_request_rub: NonNegative
    chars_per_request: Annotated[int, Field(gt=0)] = 250
    max_tts_chars: Annotated[int, Field(gt=0, le=5000)] = 3000
    # Распознавание (API v1, короткое аудио) — за каждые начатые 15 секунд.
    price_stt_per_15s_rub: NonNegative
    max_recording_seconds: Annotated[int, Field(gt=0, le=30)] = 30
    timeout_seconds: PositiveWeight = 60

    def tts_cost_rub(self, chars: int) -> float:
        """Стоимость озвучки текста с запасом: запрос на каждые chars_per_request символов."""
        return -(-max(chars, 1) // self.chars_per_request) * self.price_tts_per_request_rub

    def stt_cost_rub(self, seconds: float) -> float:
        """Стоимость распознавания: каждые начатые 15 секунд."""
        return -(-max(seconds, 0.001) // 15) * self.price_stt_per_15s_rub


SandboxBackend = Literal["docker", "wsl2"]


class SandboxConfig(_Strict):
    backend: SandboxBackend
    fallback_backend: SandboxBackend | None = None
    time_limit_seconds: PositiveWeight
    memory_limit_mb: Annotated[int, Field(gt=0)]
    network_enabled: bool
    # Образ Docker с ege-runner (ADR-0014); собирается из Dockerfile репозитория.
    docker_image: str = "ege-tutor:latest"


class AppConfig(_Strict):
    app: AppSection
    exams: dict[Subject, ExamDateConfig]
    ai: AIConfig
    speech: SpeechConfig
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


class EvidenceConfig(_Strict):
    recency_decay: Annotated[float, Field(gt=0.0, le=1.0)]
    confidence_scale: PositiveWeight


class ForgettingConfig(_Strict):
    initial_stability_days: PositiveWeight
    review_threshold: Annotated[float, Field(gt=0.0, lt=1.0)]
    success_threshold: Factor
    min_review_gap_days: Annotated[float, Field(ge=0.0)]
    stability_growth: Annotated[float, Field(ge=1.0)]
    max_stability_days: PositiveWeight
    failure_threshold: Factor
    stability_after_failure: Factor

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.failure_threshold > self.success_threshold:
            raise ValueError("failure_threshold не может быть больше success_threshold")
        if self.max_stability_days < self.initial_stability_days:
            raise ValueError("max_stability_days меньше initial_stability_days")
        return self


class MistakesConfig(_Strict):
    freshness_days: PositiveWeight
    close_after_independent: Annotated[int, Field(ge=1)]
    category_base: dict[MistakeCategory, PositiveWeight]

    @model_validator(mode="after")
    def _all_categories(self) -> Self:
        missing = set(MistakeCategory) - set(self.category_base)
        if missing:
            raise ValueError(f"нет базового приоритета для: {', '.join(sorted(missing))}")
        return self


class AttemptsConfig(_Strict):
    hint_carryover_hours: PositiveWeight


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
    evidence: EvidenceConfig
    forgetting: ForgettingConfig
    attempts: AttemptsConfig
    mistakes: MistakesConfig


# ── diagnostics.toml ────────────────────────────────────────────────────────


class DiagnosticsBudget(_Strict):
    max_tasks_per_subject: Annotated[int, Field(gt=0)]
    max_minutes_per_subject: Annotated[int, Field(gt=0)]


class DiagnosticsStopping(_Strict):
    target_half_width_primary: PositiveWeight
    forecast_interval: Annotated[float, Field(gt=0.0, lt=1.0)]
    min_information_gain: Annotated[float, Field(ge=0.0)]


class DiagnosticsModel(_Strict):
    """Модель «уровень ученика против сложности задачи» (ADR-0016)."""

    model_version: Annotated[str, Field(min_length=1)]
    ability_prior_sd: PositiveWeight
    item_offset_sd: PositiveWeight
    grid_step: Annotated[float, Field(gt=0.0, le=1.0)]
    ability_grid_limit: PositiveWeight
    offset_grid_limit: PositiveWeight
    guess: Annotated[float, Field(ge=0.0, lt=1.0)]
    slow_evidence: Factor
    first_difficulty: Annotated[int, Field(ge=1, le=5)]
    reference_difficulty: Annotated[int, Field(ge=1, le=5)]


class DiagnosticsRules(_Strict):
    # Диагностика всегда без подсказок и без ИИ: включить их через конфиг нельзя.
    hints_allowed: Literal[False]
    ai_allowed: Literal[False]
    allowed_verification_statuses: Annotated[list[VerificationStatus], Field(min_length=1)]


class DiagnosticsConfig(_Strict):
    budget: DiagnosticsBudget
    stopping: DiagnosticsStopping
    model: DiagnosticsModel
    rules: DiagnosticsRules


# ── planner.toml ────────────────────────────────────────────────────────────


Share = Annotated[float, Field(gt=0.0, le=1.0)]
Positive = Annotated[int, Field(gt=0)]


class PlannerDay(_Strict):
    default_utc_offset_hours: Annotated[int, Field(ge=-12, le=14)]
    default_minutes: Positive
    min_plan_minutes: Annotated[int, Field(ge=0)]
    fatigue_factors: Annotated[
        list[Annotated[float, Field(ge=0.0, le=1.0)]], Field(min_length=5, max_length=5)
    ]

    def fatigue_factor(self, fatigue: int | None) -> float:
        return 1.0 if fatigue is None else self.fatigue_factors[fatigue - 1]


class PlannerPlan(_Strict):
    mandatory_share: Share
    user_change_share: Annotated[float, Field(ge=0.0, le=1.0)]
    time_factor: PositiveWeight
    default_task_minutes: Positive
    max_tasks_per_item: Positive
    review_tasks: Positive
    mistake_tasks: Positive
    diagnostic_minutes: Positive
    min_subject_share: Annotated[float, Field(ge=0.0, le=0.5)]
    unstudied_mastery: Factor
    min_gap_factor: Factor
    carry_search_days: Positive


class PlannerExcuses(_Strict):
    warn_days: Positive
    window_days: Positive


class PlannerControl(_Strict):
    tasks: Positive
    min_tasks: Positive
    pass_share: Share
    slow_factor: PositiveWeight
    fresh_days: Annotated[int, Field(ge=0)]
    skip_days: Positive

    @model_validator(mode="after")
    def _min_not_above_tasks(self) -> Self:
        if self.min_tasks > self.tasks:
            raise ValueError("min_tasks не может быть больше tasks")
        return self


class PlannerDiscipline(_Strict):
    window_days: Positive
    green: Share
    yellow: Share
    orange: Share
    red_streak_days: Positive

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> Self:
        if not self.green > self.yellow > self.orange:
            raise ValueError("пороги дисциплины должны убывать: green > yellow > orange")
        return self


class PlannerConfig(_Strict):
    day: PlannerDay
    plan: PlannerPlan
    excuses: PlannerExcuses
    control: PlannerControl
    discipline: PlannerDiscipline


# ── загрузка ────────────────────────────────────────────────────────────────


def project_root() -> Path:
    """Корень репозитория (src/ege_tutor/config.py → ../..)."""
    return Path(__file__).resolve().parents[2]


def default_config_dir() -> Path:
    return project_root() / "config"


class Settings(_Strict):
    config_dir: Path
    app: AppConfig
    mastery: MasteryConfig
    diagnostics: DiagnosticsConfig
    planner: PlannerConfig

    @property
    def data_dir(self) -> Path:
        """Папка личных данных: EGE_TUTOR_DATA_DIR → app.data_dir (относительно корня проекта)."""
        env = os.environ.get(DATA_DIR_ENV)
        path = Path(env) if env else self.app.app.data_dir
        return path if path.is_absolute() else project_root() / path

    @property
    def content_dir(self) -> Path:
        """Публичный учебный контент из репозитория: каталог тем, структура экзаменов."""
        return project_root() / "content"


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


def _with_ai_overrides(app: AppConfig) -> AppConfig:
    """Переменные окружения сервера поверх [ai] из app.toml: провайдер, модель, бюджет."""
    changes: dict[str, object] = {}
    for env, key in (
        (AI_PROVIDER_ENV, "provider"),
        (AI_MODEL_ENV, "model"),
        (AI_BUDGET_ENV, "monthly_budget_rub"),
    ):
        value = os.environ.get(env, "").strip()
        if value:
            changes[key] = value
    if not changes:
        return app
    try:
        ai = AIConfig.model_validate(app.ai.model_dump() | changes)
    except ValidationError as e:
        raise ConfigError(f"ошибка в переменных окружения ИИ:\n{e}") from e
    return app.model_copy(update={"ai": ai})


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
        app=_with_ai_overrides(_read_toml(config_dir / "app.toml", AppConfig)),
        mastery=_read_toml(config_dir / "mastery.toml", MasteryConfig),
        diagnostics=_read_toml(config_dir / "diagnostics.toml", DiagnosticsConfig),
        planner=_read_toml(config_dir / "planner.toml", PlannerConfig),
    )
