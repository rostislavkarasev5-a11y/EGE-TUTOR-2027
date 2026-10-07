"""Загрузка файлов с задачами через сайт: .yaml/.csv или .zip с файлом задач и файлами к ним.

Файлы складываются во временную папку внутри папки данных. Архив распаковывается
с проверками: без абсолютных путей и «..», с лимитами на размер и число файлов.
"""

import secrets
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

TASK_SUFFIXES = {".yaml", ".yml", ".csv"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ZIP_FILES = 500
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
STALE_SECONDS = 24 * 60 * 60
_CHUNK = 1024 * 1024


class UploadError(Exception):
    """Загруженный файл не подходит. Текст понятен пользователю."""


class _TooLarge(Exception):
    pass


def _token_ok(token: str) -> bool:
    return 16 <= len(token) <= 64 and all(c.isalnum() or c in "-_" for c in token)


def upload_dir(root: Path, token: str) -> Path:
    if not _token_ok(token):
        raise UploadError("неверная ссылка на загрузку, загрузи файл заново")
    return root / token


def remove_stale(root: Path, now: float | None = None) -> None:
    """Удалить загрузки старше суток, которые так и не записали в базу."""
    if not root.is_dir():
        return
    now = time.time() if now is None else now
    for folder in root.iterdir():
        if folder.is_dir() and now - folder.stat().st_mtime > STALE_SECONDS:
            shutil.rmtree(folder, ignore_errors=True)


def _copy_limited(source: BinaryIO, target: Path, limit: int) -> int:
    written = 0
    with target.open("wb") as out:
        while chunk := source.read(_CHUNK):
            written += len(chunk)
            if written > limit:
                raise _TooLarge
            out.write(chunk)
    return written


def _copy_upload(stream: BinaryIO, target: Path) -> None:
    try:
        _copy_limited(stream, target, MAX_UPLOAD_BYTES)
    except _TooLarge as e:
        raise UploadError(f"файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ") from e


def _task_files(folder: Path) -> list[Path]:
    """Файлы задач в корне папки загрузки."""
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in TASK_SUFFIXES)


def _safe_member(name: str) -> PurePosixPath | None:
    """Путь внутри архива или None для папок. Опасные пути — ошибка."""
    if name.endswith("/"):
        return None
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name:
        raise UploadError(f"в архиве недопустимый путь: {name}")
    return path


def _unpack_zip(archive: Path, target: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > MAX_ZIP_FILES:
                raise UploadError(f"в архиве больше {MAX_ZIP_FILES} файлов")
            total = 0
            for member in members:
                path = _safe_member(member.filename)
                if path is None:
                    continue
                dest = target.joinpath(*path.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src:
                    total += _copy_limited(src, dest, MAX_UNPACKED_BYTES - total)
    except zipfile.BadZipFile as e:
        raise UploadError("архив повреждён или это не .zip") from e
    except _TooLarge as e:
        raise UploadError("архив после распаковки больше 200 МБ") from e


def save_upload(root: Path, file_name: str, stream: BinaryIO) -> tuple[str, Path]:
    """Сохранить загрузку. Возвращает (токен загрузки, путь к файлу задач)."""
    name = PurePosixPath(file_name.replace("\\", "/")).name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in TASK_SUFFIXES | {".zip"}:
        raise UploadError("нужен файл .yaml, .csv или архив .zip с файлом задач и файлами к нему")
    token = secrets.token_urlsafe(24)
    folder = root / token
    folder.mkdir(parents=True)
    try:
        if suffix != ".zip":
            target = folder / name
            _copy_upload(stream, target)
            return token, target
        archive = folder.parent / f"{token}.zip"
        try:
            _copy_upload(stream, archive)
            _unpack_zip(archive, folder)
        finally:
            archive.unlink(missing_ok=True)
        found = _task_files(folder)
        if len(found) != 1:
            raise UploadError(
                "в корне архива должен лежать ровно один файл задач (.yaml или .csv), "
                f"найдено: {len(found)}"
            )
        return token, found[0]
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def find_task_file(root: Path, token: str) -> Path:
    """Файл задач ранее загруженной пачки."""
    folder = upload_dir(root, token)
    found = _task_files(folder) if folder.is_dir() else []
    if len(found) != 1:
        raise UploadError("загрузка не найдена или устарела, загрузи файл заново")
    return found[0]


def discard(root: Path, token: str) -> None:
    shutil.rmtree(upload_dir(root, token), ignore_errors=True)
