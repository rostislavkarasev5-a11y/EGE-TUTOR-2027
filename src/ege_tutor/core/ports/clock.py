import datetime as dt
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Источник текущего времени.

    Отдельный порт нужен, чтобы тестировать логику, зависящую от времени
    (забывание, дедлайны, таймеры), без реального ожидания.
    """

    def now(self) -> dt.datetime:
        """Текущий момент с часовым поясом."""
        ...

    def today(self) -> dt.date:
        """Текущая дата в часовом поясе пользователя."""
        ...
