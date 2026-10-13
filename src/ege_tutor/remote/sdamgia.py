"""Скачивание рисунков к задачам Решу ЕГЭ (ADR-0021).

Только https и только адреса *.sdamgia.ru: сервер не должен по загруженной
странице ходить на произвольные адреса (в том числе во внутреннюю сеть).
Перенаправления на другие сайты не выполняются.
"""

import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ege_tutor.core.ports import RemoteFileError

ALLOWED_DOMAIN = "sdamgia.ru"
TIMEOUT_SECONDS = 20
USER_AGENT = "EGE-TUTOR-2027 (личный тренажёр; скачивает рисунки к сохранённой странице)"


def allowed_url(url: str) -> bool:
    """Можно ли скачивать по этой ссылке."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and parts.username is None
        and parts.port in (None, 443)
        and (host == ALLOWED_DOMAIN or host.endswith("." + ALLOWED_DOMAIN))
    )


class _SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise urllib.error.HTTPError(newurl, code, "перенаправление на чужой сайт", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SdamgiaFiles:
    """Реализация порта RemoteFiles для сайтов Решу ЕГЭ."""

    def __init__(self, timeout: float = TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_SameSiteRedirects)

    def fetch(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        if not allowed_url(url):
            raise RemoteFileError(f"адрес не с сайта Решу ЕГЭ: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                data = response.read(max_bytes + 1)
                mime = response.headers.get_content_type()
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise RemoteFileError(f"не удалось скачать {url}: {e}") from e
        if len(data) > max_bytes:
            raise RemoteFileError(f"файл больше {max_bytes // 1024} КБ: {url}")
        return data, mime
