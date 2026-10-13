from typing import Protocol, runtime_checkable


class RemoteFileError(Exception):
    """Файл не удалось скачать. Текст понятен пользователю."""


@runtime_checkable
class RemoteFiles(Protocol):
    """Скачивание отдельных файлов по ссылке (рисунки к задачам Решу ЕГЭ, ADR-0021).

    Порт нужен, чтобы CORE не ходил в интернет сам, а тесты работали без сети.
    Реализация сама решает, с каких адресов можно скачивать.
    """

    def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        """Скачать файл. Возвращает (содержимое, MIME-тип). Ошибка — RemoteFileError."""
        ...
