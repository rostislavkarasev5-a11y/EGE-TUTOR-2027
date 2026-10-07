import datetime as dt


class SystemClock:
    """Реальное время компьютера в его локальном часовом поясе."""

    def now(self) -> dt.datetime:
        return dt.datetime.now().astimezone()

    def today(self) -> dt.date:
        return self.now().date()


class FixedClock:
    """Время, заданное вручную. Для тестов и воспроизводимых расчётов."""

    def __init__(self, moment: dt.datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FixedClock требует время с часовым поясом")
        self._moment = moment

    def now(self) -> dt.datetime:
        return self._moment

    def today(self) -> dt.date:
        return self._moment.date()

    def advance(self, delta: dt.timedelta) -> None:
        self._moment += delta
