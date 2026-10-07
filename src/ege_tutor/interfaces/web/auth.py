"""Вход на сайт: пароль владельца, секрет подписи cookie и защита от подбора (ADR-0013).

Пароль хранится только как хеш Argon2 в папке данных (вне Git). Регистрации нет:
пользователь один — владелец, пароль задаётся командой `ege-web set-password`.
"""

import hashlib
import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 10
SECRET_KEY_ENV = "EGE_WEB_SECRET_KEY"


def web_dir(data_dir: Path) -> Path:
    """Папка сайта внутри папки личных данных: пароль, секрет, загрузки."""
    return data_dir / "web"


def _write_private(path: Path, text: str) -> None:
    """Записать файл, который может читать только владелец (на Linux — права 600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


class PasswordStore:
    """Хеш пароля владельца в файле."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._hasher = PasswordHasher()

    def is_set(self) -> bool:
        return self.path.is_file() and bool(self.path.read_text(encoding="utf-8").strip())

    def set(self, password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
        _write_private(self.path, self._hasher.hash(password) + "\n")

    def fingerprint(self) -> str:
        """Отпечаток текущего пароля: после смены пароля старые сессии перестают действовать."""
        if not self.is_set():
            return ""
        stored = self.path.read_text(encoding="utf-8").strip()
        return hashlib.sha256(stored.encode()).hexdigest()[:16]

    def verify(self, password: str) -> bool:
        if not self.is_set():
            return False
        stored = self.path.read_text(encoding="utf-8").strip()
        try:
            self._hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
        if self._hasher.check_needs_rehash(stored):
            _write_private(self.path, self._hasher.hash(password) + "\n")
        return True


def load_secret_key(data_dir: Path) -> str:
    """Секрет подписи cookie: из переменной окружения или из файла (создаётся один раз)."""
    env = os.environ.get(SECRET_KEY_ENV, "").strip()
    if env:
        return env
    path = web_dir(data_dir) / "secret.key"
    if path.is_file():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    key = secrets.token_urlsafe(48)
    _write_private(path, key + "\n")
    return key


class LoginThrottle:
    """После max_failures неверных паролей подряд вход с этого адреса блокируется."""

    def __init__(
        self,
        max_failures: int = 5,
        lock_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, key: str) -> int:
        """Сколько секунд ещё действует блокировка (0 — вход разрешён)."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            left = until - self._clock()
            if left <= 0:
                del self._locked_until[key]
                return 0
            return int(left) + 1

    def failure(self, key: str) -> None:
        with self._lock:
            count = self._failures.get(key, 0) + 1
            if count >= self.max_failures:
                self._locked_until[key] = self._clock() + self.lock_seconds
                count = 0
            self._failures[key] = count

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
