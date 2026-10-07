"""Программы на Python к задачам информатики: тест-кейсы и запуски (Phase 3)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TaskTestCase:
    """Маленький пример с известным ответом для проверки программы к задаче.

    Программа получает input на стандартный ввод, а файлы из files — вместо файлов
    задачи с теми же именами (например, короткий numbers.txt вместо настоящего).
    """

    position: int  # номер теста, с 1
    input: str
    output: str
    files: tuple[tuple[str, str], ...] = ()  # (имя файла, содержимое)


class CodeVerdict(StrEnum):
    """Итог проверки программы: запуск в Sandbox и сравнение вывода с тестами."""

    OK = "OK"
    WRONG_ANSWER = "WRONG_ANSWER"
    TIME_LIMIT = "TIME_LIMIT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"


CODE_VERDICT_LABELS: dict[CodeVerdict, str] = {
    CodeVerdict.OK: "Программа отработала",
    CodeVerdict.WRONG_ANSWER: "Неверный вывод на тесте",
    CodeVerdict.TIME_LIMIT: "Превышено время",
    CodeVerdict.MEMORY_LIMIT: "Превышена память",
    CodeVerdict.RUNTIME_ERROR: "Ошибка во время работы",
    CodeVerdict.SYNTAX_ERROR: "Синтаксическая ошибка",
}


@dataclass(frozen=True)
class CodeRun:
    """Один запуск программы к задаче. Никогда не удаляется (как и попытки)."""

    id: int
    task_id: int
    attempt_id: int | None
    created_at: dt.datetime
    code: str
    verdict: CodeVerdict
    tests_total: int
    tests_passed: int
    failed_test: int | None  # номер первого непройденного теста
    stdout: str  # вывод основного запуска (или теста, на котором ошибка)
    stderr: str
    exit_code: int | None
    duration_seconds: float

    @property
    def label(self) -> str:
        return CODE_VERDICT_LABELS[self.verdict]

    @property
    def answer_guess(self) -> str | None:
        """Последняя непустая строка вывода — обычно это и есть ответ к заданию."""
        if self.verdict != CodeVerdict.OK:
            return None
        lines = [line.strip() for line in self.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else None
