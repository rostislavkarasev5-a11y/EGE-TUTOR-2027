"""EGE-TUTOR-2027 — персональная система подготовки к ЕГЭ по профильной математике и информатике."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ege-tutor")
except PackageNotFoundError:  # пакет не установлен (например, запуск из исходников без uv)
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
