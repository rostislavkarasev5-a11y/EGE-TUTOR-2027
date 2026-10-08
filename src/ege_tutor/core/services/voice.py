"""Голос репетитора: озвучка ответов и распознавание вопросов (Phase 6.5, ADR-0018).

Правила, которые обеспечивает CORE (а не SpeechKit):
- голос работает только там, где разрешён ИИ: в диагностике, контрольной, пробнике и экзамене
  его нет; траты входят в тот же месячный лимит, что и ИИ;
- озвучивается только то, что уже есть в базе (ответы ИИ, реплики репетитора, подсказки),
  а не произвольный текст; готовый звук кэшируется, повторное прослушивание бесплатно;
- голос не хранится: распознанный текст возвращается ученику, отправляет его он сам;
  ответ на задачу голосом не отправляется;
- каждое обращение записывается в ai_call с примерной стоимостью.
"""

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ege_tutor.config import SpeechConfig
from ege_tutor.core.domain import (
    AICallStatus,
    AIPurpose,
    AIStatus,
    AIUsage,
    AttemptStatus,
    SpeechError,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import Clock, Repository, SpeechService
from ege_tutor.core.services.assistant import AI_FORBIDDEN_MODES

SAMPLE_RATES = (8000, 16000, 48000)
MIN_RECORDING_SECONDS = 0.3
_CLIP_NAME = re.compile(r"^[0-9a-f]{32}\.mp3$")

# Как читать вслух то, что на экране записано символами. Порядок важен: сначала длинное.
# Знаки между буквами трогаем только в формулах (латиница и цифры): «какой-то» и «км/ч»
# остаются как есть.
_L = r"(?<=[0-9a-zA-Z)])"
_R = r"(?=[0-9a-zA-Z(])"
_SPOKEN = (
    (re.compile(r"sqrt\s*\("), " корень из ("),
    (re.compile(r"√"), " корень из "),
    (re.compile(r"log_(\w+)\s*\("), r" логарифм по основанию \1 от ("),
    (re.compile(r"\^\s*2(?!\d)"), " в квадрате"),
    (re.compile(r"\^\s*3(?!\d)"), " в кубе"),
    (re.compile(r"\^"), " в степени "),
    (re.compile(r"≤|<="), " меньше или равно "),
    (re.compile(r"≥|>="), " больше или равно "),
    (re.compile(r"≠|!="), " не равно "),
    (re.compile(r"(?<=\s)<(?=\s)"), " меньше "),
    (re.compile(r"(?<=\s)>(?=\s)"), " больше "),
    (re.compile(_L + r"\s*\*\s*" + _R), " умножить на "),
    (re.compile(r"·|×"), " умножить на "),
    (re.compile(_L + r"\s*/\s*" + _R), " делить на "),
    (re.compile(r"(?<=\s)-(?=\s)|−|" + _L + "-" + _R), " минус "),
    (re.compile(_L + r"\s*\+\s*" + _R), " плюс "),
    (re.compile(_L + r"\s*=\s*(?=[0-9a-zA-Z(-])"), " равно "),
    (re.compile(r"π"), " пи "),
    (re.compile(r"[`*_#]"), " "),
)


def speakable(text: str) -> str:
    """Текст для чтения вслух: формулы словами там, где это можно сделать правилами."""
    result = text
    for pattern, spoken in _SPOKEN:
        result = pattern.sub(spoken, result)
    return " ".join(result.split())


@dataclass(frozen=True)
class SpeechClip:
    """Озвученный текст: имя файла в кэше и был ли он уже готов (тогда бесплатно)."""

    name: str
    cached: bool


class VoiceService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        speech: SpeechService,
        config: SpeechConfig,
        status: Callable[[], AIStatus],
        cache_dir: Path,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._speech = speech
        self.config = config
        self._status = status
        self._cache_dir = cache_dir

    def _require_available(self) -> None:
        status = self._status()
        if not status.speech_available:
            raise AppError(f"голос недоступен: {status.speech_reason}")

    def _check_attempt(self, attempt_id: int | None) -> None:
        if attempt_id is None:
            return
        attempt = self._repo.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        if attempt.mode in AI_FORBIDDEN_MODES:
            raise AppError("в диагностике, контрольной, пробнике и экзамене голоса нет")

    def _record(
        self,
        purpose: AIPurpose,
        status: AICallStatus,
        units: int,
        cost: float,
        request_hash: str,
        *,
        error: str | None = None,
        attempt_id: int | None = None,
        task_id: int | None = None,
    ) -> None:
        # Для голоса в input_tokens пишется объём: символы озвучки или секунды записи.
        model = f"speechkit:{self._speech.voice}"
        self._repo.add_ai_call(
            purpose=purpose,
            status=status,
            model=model,
            usage=AIUsage(model, units, 0, request_hash),
            cost_rub=cost,
            at=self._clock.now(),
            error=error,
            attempt_id=attempt_id,
            task_id=task_id,
        )

    # ── озвучка ─────────────────────────────────────────────────────────────

    def _clip_name(self, text: str) -> str:
        key = "\n".join(
            (self._speech.voice, self.config.role, str(self.config.speed), text)
        ).encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:32] + ".mp3"

    def speak(
        self, text: str, *, attempt_id: int | None = None, task_id: int | None = None
    ) -> SpeechClip:
        """Озвучить текст из базы. Готовый звук берётся из кэша и не стоит ничего."""
        self._check_attempt(attempt_id)
        spoken = text.strip()[: self.config.max_tts_chars]
        if not spoken:
            raise AppError("озвучивать нечего")
        name = self._clip_name(spoken)
        path = self._cache_dir / name
        if path.is_file():
            return SpeechClip(name, cached=True)
        self._require_available()
        chars = len(spoken)
        try:
            audio = self._speech.synthesize(spoken)
        except SpeechError as e:
            self._record(
                AIPurpose.SPEECH,
                AICallStatus.ERROR,
                chars,
                self.config.tts_cost_rub(chars) if e.billable else 0.0,
                name[:16],
                error=str(e),
                attempt_id=attempt_id,
                task_id=task_id,
            )
            raise AppError(f"озвучить не получилось: {e}") from e
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_bytes(audio)
        partial.replace(path)
        self._record(
            AIPurpose.SPEECH,
            AICallStatus.OK,
            chars,
            self.config.tts_cost_rub(chars),
            name[:16],
            attempt_id=attempt_id,
            task_id=task_id,
        )
        return SpeechClip(name, cached=False)

    def clip_path(self, name: str) -> Path | None:
        """Файл озвучки по имени из ссылки; чужие имена и пути не принимаются."""
        if not _CLIP_NAME.fullmatch(name):
            return None
        path = self._cache_dir / name
        return path if path.is_file() else None

    # ── распознавание ───────────────────────────────────────────────────────

    def listen(self, attempt_id: int, pcm: bytes, sample_rate: int) -> str:
        """Распознать вопрос, заданный голосом. Текст возвращается ученику для проверки."""
        self._check_attempt(attempt_id)
        attempt = self._repo.get_attempt(attempt_id)
        if attempt is not None and attempt.status == AttemptStatus.ABANDONED:
            raise AppError("попытка брошена: начни задачу заново")
        if sample_rate not in SAMPLE_RATES:
            raise AppError("неподдерживаемая частота записи")
        if len(pcm) % 2:
            raise AppError("запись повреждена")
        seconds = len(pcm) / (2 * sample_rate)
        if seconds < MIN_RECORDING_SECONDS:
            raise AppError("запись слишком короткая: нажми и говори")
        if seconds > self.config.max_recording_seconds + 0.5:
            raise AppError(
                f"запись длиннее {self.config.max_recording_seconds} секунд: спроси короче"
            )
        self._require_available()
        request_hash = hashlib.sha256(pcm).hexdigest()[:16]
        units = math.ceil(seconds)
        cost = self.config.stt_cost_rub(seconds)
        try:
            text = self._speech.recognize(pcm, sample_rate)
        except SpeechError as e:
            self._record(
                AIPurpose.LISTEN,
                AICallStatus.ERROR,
                units,
                cost if e.billable else 0.0,
                request_hash,
                error=str(e),
                attempt_id=attempt_id,
            )
            raise AppError(f"распознать не получилось: {e}") from e
        self._record(
            AIPurpose.LISTEN, AICallStatus.OK, units, cost, request_hash, attempt_id=attempt_id
        )
        if not text.strip():
            raise AppError("речь не разобрана: попробуй ещё раз, ближе к микрофону")
        return text.strip()
