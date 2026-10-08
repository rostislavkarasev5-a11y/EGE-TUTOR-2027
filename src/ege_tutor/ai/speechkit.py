"""Голос репетитора через Yandex SpeechKit (Phase 6.5, ADR-0018).

Озвучка — API v3 (REST `utteranceSynthesis`, звук MP3), распознавание — API v1 (короткое аудио
до 30 секунд, 16-битный PCM). Запросы — стандартной библиотекой (urllib), ключ тот же, что у ИИ.
Адаптер ничего не хранит и не решает: что озвучить, кэш, траты и лимит — забота CORE.
"""

import base64
import binascii
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ege_tutor.ai.yandex import Opener, _default_opener
from ege_tutor.config import SpeechConfig
from ege_tutor.core.domain import SpeechError

_ERROR_BODY_CHARS = 200
_ROLES_HINT = (
    "SpeechKit не принял ключ: у сервисного аккаунта нужны роли ai.speechkit-tts.user и "
    "ai.speechkit-stt.user, а у ключа — области yc.ai.speechkitTts.execute и "
    "yc.ai.speechkitStt.execute"
)


def _http_error(error: urllib.error.HTTPError) -> str:
    if error.code in (401, 403):
        return _ROLES_HINT
    if error.code == 429:
        return "слишком много запросов к SpeechKit. Подожди минуту"
    detail = ""
    try:
        body = json.loads(error.read() or b"{}")
        if isinstance(body, dict):
            message = body.get("error_message") or body.get("message")
            if not isinstance(message, str):
                inner = body.get("error")
                message = inner.get("message") if isinstance(inner, dict) else None
            if isinstance(message, str):
                detail = ": " + message[:_ERROR_BODY_CHARS]
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, OSError):
        pass
    return f"SpeechKit ответил ошибкой {error.code}{detail}"


def _audio_chunks(raw: bytes) -> bytes:
    """Звук из ответа API v3: поток объектов JSON, в каждом — кусок звука в base64."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SpeechError("SpeechKit вернул не JSON", billable=True) from None
    stripped = text.strip()
    objects: list[Any] = []
    if stripped.startswith("["):  # на случай, если ответ пришёл одним массивом
        try:
            objects = json.loads(stripped)
        except json.JSONDecodeError:
            objects = []
    else:
        decoder = json.JSONDecoder()
        position = 0
        while position < len(stripped):
            while position < len(stripped) and stripped[position] in " \r\n\t,":
                position += 1
            if position >= len(stripped):
                break
            try:
                obj, position = decoder.raw_decode(stripped, position)
            except json.JSONDecodeError:
                raise SpeechError("SpeechKit вернул ответ не по формату", billable=True) from None
            objects.append(obj)
    audio = bytearray()
    for obj in objects:
        result = obj.get("result", obj) if isinstance(obj, dict) else None
        chunk = result.get("audioChunk") if isinstance(result, dict) else None
        data = chunk.get("data") if isinstance(chunk, dict) else None
        if isinstance(data, str):
            try:
                audio += base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise SpeechError("SpeechKit вернул повреждённый звук", billable=True) from None
    if not audio:
        raise SpeechError("SpeechKit вернул пустой звук", billable=True)
    return bytes(audio)


class YandexSpeechService:
    def __init__(
        self,
        config: SpeechConfig,
        api_key: str,
        *,
        tts_url: str | None = None,
        stt_url: str | None = None,
        opener: Opener | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("нужен ключ API")
        self._config = config
        self._api_key = api_key
        self._tts_url = tts_url or config.tts_url
        self._stt_url = stt_url or config.stt_url
        self._open = opener or _default_opener

    def __repr__(self) -> str:  # ключ не должен попасть в логи даже случайно
        return f"YandexSpeechService(voice={self.voice!r})"

    @property
    def is_available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    @property
    def voice(self) -> str:
        return self._config.voice

    def _send(self, request: urllib.request.Request) -> bytes:
        request.add_header("Authorization", f"Api-Key {self._api_key}")
        request.add_header("x-data-logging-enabled", "false")
        try:
            with self._open(request, self._config.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            raise SpeechError(_http_error(e)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SpeechError("нет связи с SpeechKit. Попробуй позже") from None

    def synthesize(self, text: str) -> bytes:
        hints: list[dict[str, object]] = [{"voice": self._config.voice}]
        if self._config.role:
            hints.append({"role": self._config.role})
        hints.append({"speed": self._config.speed})
        body = {
            "text": text,
            "hints": hints,
            "outputAudioSpec": {"containerAudio": {"containerAudioType": "MP3"}},
            # длинный текст SpeechKit сам делит на части
            "unsafeMode": True,
        }
        request = urllib.request.Request(
            self._tts_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return _audio_chunks(self._send(request))

    def recognize(self, pcm: bytes, sample_rate: int) -> str:
        query = urllib.parse.urlencode(
            {
                "lang": "ru-RU",
                "topic": "general",
                "format": "lpcm",
                "sampleRateHertz": sample_rate,
            }
        )
        request = urllib.request.Request(
            f"{self._stt_url}?{query}",
            data=pcm,
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        raw = self._send(request)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SpeechError("SpeechKit вернул не JSON", billable=True) from None
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, str):
            raise SpeechError("SpeechKit вернул ответ не по формату", billable=True)
        return result.strip()


class DisabledSpeechService:
    """Голоса нет: выключен в настройках, нет ключа или выключен ИИ."""

    def __init__(self, reason: str = "голос выключен в настройках") -> None:
        self._reason = reason

    @property
    def is_available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def voice(self) -> str:
        return "—"

    def synthesize(self, text: str) -> bytes:
        raise SpeechError(self._reason)

    def recognize(self, pcm: bytes, sample_rate: int) -> str:
        raise SpeechError(self._reason)
