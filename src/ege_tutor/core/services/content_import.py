"""Конвейер импорта задач (ADR-0007, ADR-0011).

файл (YAML / CSV) → разбор → нормализация → проверка → поиск дублей → отчёт → запись пачкой.

По умолчанию импорт — только предпросмотр. Записываются лишь задачи без ошибок;
ошибочные перечисляются в отчёте с номером задачи и понятной причиной.
"""

import csv
import hashlib
import io
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ege_tutor.core.domain import (
    HINT_LEVELS,
    AnswerKind,
    AnswerType,
    ExamSpec,
    ImportIssue,
    ImportReport,
    Subject,
    TaskDraft,
    TaskHint,
    TaskSource,
    TaskTestCase,
    VerificationStatus,
)

KNOWN_FIELDS = {
    "subject",
    "exam_item",
    "statement",
    "answer",
    "answer_type",
    "solution",
    "difficulty",
    "time_norm_minutes",
    "source",
    "source_ref",
    "source_version",
    "verification_status",
    "skills",
    "assets",
    "hints",
    "tests",
}
# При импорте можно указать только эти статусы. AUTO_CHECKED ставит сама система
# после автоматической проверки, DISPUTED/REJECTED — при разборе ошибок в задачах.
IMPORTABLE_STATUSES = {VerificationStatus.UNVERIFIED, VerificationStatus.REVIEWED}
MAX_ASSET_BYTES = 50 * 1024 * 1024
MAX_TESTS = 50
MAX_TEST_BYTES = 1_000_000


class ImportFileError(Exception):
    """Файл нельзя прочитать целиком (формат, кодировка, структура)."""


def content_hash(subject: Subject, exam_item: int, statement: str) -> str:
    """Хэш для поиска дублей: регистр и лишние пробелы не важны."""
    normalized = " ".join(statement.lower().split())
    return hashlib.sha256(f"{subject}|{exam_item}|{normalized}".encode()).hexdigest()


# ── чтение файлов ───────────────────────────────────────────────────────────


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):  # Excel в Windows часто сохраняет CSV в cp1251
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("не удалось определить кодировку файла (нужна UTF-8 или Windows-1251)")


def _split_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[;,]", str(value)) if part.strip()]


def read_records(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Прочитать файл в список записей. Возвращает формат и записи."""
    suffix = path.suffix.lower()
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ImportFileError(f"не удалось открыть файл: {e}") from e
    text = _decode(raw)

    if suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ImportFileError(f"ошибка YAML: {e}") from e
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            raise ImportFileError("в YAML-файле нужен список tasks (см. content/templates)")
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ImportFileError("defaults должен быть словарём")
        records = []
        for item in data["tasks"]:
            if not isinstance(item, dict):
                raise ImportFileError("каждая задача в tasks должна быть словарём")
            records.append({**defaults, **item})
        return "yaml", records

    if suffix == ".csv":
        first_line = text.splitlines()[0] if text else ""
        delimiter = max(";,\t", key=first_line.count)  # Excel с русской локалью ставит «;»
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise ImportFileError("в CSV-файле нет строки заголовков")
        records = [
            {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            for row in reader
        ]
        return "csv", [{k: v for k, v in r.items() if v not in ("", None)} for r in records]

    shown = suffix or "(без расширения)"
    raise ImportFileError(f"неподдерживаемый формат {shown}: нужен .yaml или .csv")


# ── проверка одной записи ───────────────────────────────────────────────────


class _RowChecker:
    def __init__(self, row: int, errors: list[ImportIssue], warnings: list[ImportIssue]) -> None:
        self.row = row
        self._errors = errors
        self._warnings = warnings
        self.ok = True

    def error(self, message: str) -> None:
        self.ok = False
        self._errors.append(ImportIssue(self.row, message))

    def warn(self, message: str) -> None:
        self._warnings.append(ImportIssue(self.row, message))


def _parse_enum[E](value: Any, enum_cls: type[E], field: str, check: _RowChecker) -> E | None:
    try:
        return enum_cls(str(value).strip().upper())
    except ValueError:
        allowed = ", ".join(m.value for m in enum_cls)
        check.error(f"{field}: неизвестное значение «{value}» (допустимо: {allowed})")
        return None


def _normalize_answer(answer_type: AnswerType, value: Any, check: _RowChecker) -> str | None:
    text = None if value is None else str(value).strip()
    if answer_type == AnswerType.EXTENDED:
        return text or None
    if not text:
        check.error("answer: нужен ответ")
        return None
    if answer_type == AnswerType.NUMBER:
        number = text.replace(",", ".")
        try:
            float(number)
        except ValueError:
            check.error(f"answer: «{text}» — не число (тип ответа NUMBER)")
            return None
        return number
    if answer_type == AnswerType.SEQUENCE:
        parts = text.split()
        if len(parts) < 2:
            check.error("answer: для SEQUENCE нужно несколько значений через пробел")
            return None
        return " ".join(parts)
    return text


def _parse_hints(value: Any, answer: str | None, check: _RowChecker) -> tuple[TaskHint, ...]:
    """Подсказки уровней 1–3: список по порядку или словарь {уровень: текст}.

    Уровень 4 — это solution задачи, уровень 5 — похожая задача: их здесь не задают.
    """
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        items = [(1, value)]
    elif isinstance(value, list):
        items = list(enumerate(value, start=1))
    elif isinstance(value, dict):
        items = list(value.items())
    else:
        check.error("hints: нужен список подсказок или словарь {уровень: текст}")
        return ()
    hints = []
    for raw_level, raw_text in items:
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            level = 0
        text = str(raw_text or "").strip()
        if level not in HINT_LEVELS:
            check.error("hints: уровни подсказок — 1, 2 и 3 (4 — это solution)")
            return ()
        if not text:
            check.error(f"hints: пустая подсказка уровня {level}")
            return ()
        if answer and re.search(rf"(?<![\w.,]){re.escape(answer)}(?![\w.,])", text):
            check.warn(f"hints: подсказка уровня {level} похоже содержит ответ")
        hints.append(TaskHint(level, text))
    return tuple(sorted(hints, key=lambda h: h.level))


def _parse_test_files(value: Any, position: int, check: _RowChecker) -> tuple | None:
    if value is None:
        return ()
    if not isinstance(value, dict):
        check.error(f"tests: в тесте {position} files — это словарь {{имя файла: содержимое}}")
        return None
    files = []
    for name, content in value.items():
        name = str(name).strip()
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            check.error(f"tests: в тесте {position} недопустимое имя файла «{name}»")
            return None
        files.append((name, "" if content is None else str(content)))
    return tuple(files)


def _parse_tests(
    value: Any, subject: Subject | None, check: _RowChecker
) -> tuple[TaskTestCase, ...]:
    """Тест-кейсы для программы: список {input, files, output}. Информатика, только YAML."""
    if value is None or value == "" or value == []:
        return ()
    if subject is not None and subject != Subject.INFORMATICS:
        check.error("tests: тест-кейсы бывают только у задач по информатике")
        return ()
    if not isinstance(value, list):
        check.error("tests: нужен список вида [{input: ..., output: ...}] (только в YAML)")
        return ()
    if len(value) > MAX_TESTS:
        check.error(f"tests: не больше {MAX_TESTS} тест-кейсов")
        return ()
    tests = []
    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict) or "output" not in item:
            check.error(f"tests: в тесте {position} нужно поле output (и input или files)")
            return ()
        unknown = set(item) - {"input", "output", "files"}
        if unknown:
            check.error(f"tests: в тесте {position} неизвестные поля {', '.join(sorted(unknown))}")
            return ()
        files = _parse_test_files(item.get("files"), position, check)
        if files is None:
            return ()
        test_input = "" if item.get("input") is None else str(item["input"])
        test_output = "" if item["output"] is None else str(item["output"])
        if not test_output.strip():
            check.error(f"tests: в тесте {position} пустой output")
            return ()
        size = len((test_input + test_output + "".join(c for _, c in files)).encode("utf-8"))
        if size > MAX_TEST_BYTES:
            check.error(f"tests: тест {position} больше 1 МБ")
            return ()
        tests.append(TaskTestCase(position, test_input, test_output, files))
    return tuple(tests)


def _validate_record(
    record: dict[str, Any],
    check: _RowChecker,
    specs: dict[Subject, ExamSpec],
    skill_items: Callable[[Subject], dict[str, tuple[int, ...]]],
    base_dir: Path,
    starter_bank: bool = False,
) -> TaskDraft | None:
    unknown = set(record) - KNOWN_FIELDS - {"time_norm_seconds"}
    if unknown:
        check.warn(f"неизвестные поля пропущены: {', '.join(sorted(unknown))}")

    # предмет и номер задания
    raw_subject = str(record.get("subject", "")).strip()
    subject = None
    if not raw_subject:
        check.error("subject: не указан предмет")
    else:
        try:
            subject = Subject.parse(raw_subject)
        except ValueError:
            check.error(
                f"subject: неизвестный предмет «{raw_subject}» (допустимо: math, informatics)"
            )
    spec = specs.get(subject) if subject else None
    exam_item = None
    try:
        exam_item = int(record["exam_item"])
    except KeyError:
        check.error("exam_item: не указан номер задания")
    except (TypeError, ValueError):
        check.error(f"exam_item: «{record.get('exam_item')}» — не номер задания")
    spec_item = spec.item(exam_item) if spec and exam_item is not None else None
    if spec and exam_item is not None and spec_item is None:
        check.error(f"exam_item: в экзамене нет задания №{exam_item}")

    statement = str(record.get("statement") or "").strip()
    if not statement:
        check.error("statement: пустое условие задачи")

    # источник (обязателен: ADR-0007)
    source = None
    if not record.get("source"):
        check.error("source: не указан источник")
    else:
        source = _parse_enum(record["source"], TaskSource, "source", check)
    source_ref = str(record.get("source_ref") or "").strip()
    if not source_ref:
        check.error("source_ref: не указано, откуда задача")
    source_version = str(record["source_version"]).strip() if record.get("source_version") else None

    status = VerificationStatus.UNVERIFIED
    if record.get("verification_status"):
        status = _parse_enum(
            record["verification_status"], VerificationStatus, "verification_status", check
        )
        if status is not None and status not in IMPORTABLE_STATUSES:
            check.error(
                "verification_status: при импорте можно указать только UNVERIFIED или REVIEWED"
            )
    # Исключение — стартовый банк (ADR-0016): его ответы проверены тестами репозитория.
    if (
        source == TaskSource.AI_GENERATED
        and status != VerificationStatus.UNVERIFIED
        and not starter_bank
    ):
        check.error("verification_status: задача от ИИ при импорте всегда UNVERIFIED")

    # ответ
    if record.get("answer_type"):
        answer_type = _parse_enum(record["answer_type"], AnswerType, "answer_type", check)
    elif spec_item is not None:
        answer_type = (
            AnswerType.EXTENDED
            if spec_item.answer_kind == AnswerKind.EXTENDED
            else AnswerType.NUMBER
        )
    else:
        answer_type = None
    if spec_item is not None and answer_type is not None:
        expects_extended = spec_item.answer_kind == AnswerKind.EXTENDED
        if expects_extended != (answer_type == AnswerType.EXTENDED):
            kind = "развёрнутый" if expects_extended else "краткий"
            check.error(
                f"answer_type: {answer_type} не подходит для задания №{exam_item} ({kind} ответ)"
            )
    answer = _normalize_answer(answer_type, record.get("answer"), check) if answer_type else None

    # сложность и время
    difficulty = None
    if record.get("difficulty") is not None:
        try:
            difficulty = int(record["difficulty"])
            if not 1 <= difficulty <= 5:
                raise ValueError
        except (TypeError, ValueError):
            check.error("difficulty: нужно целое число от 1 до 5")
            difficulty = None
    time_norm_seconds = None
    if record.get("time_norm_minutes") is not None:
        try:
            minutes = float(str(record["time_norm_minutes"]).replace(",", "."))
            if minutes <= 0:
                raise ValueError
            time_norm_seconds = round(minutes * 60)
        except ValueError:
            check.error("time_norm_minutes: нужно положительное число минут")

    # навыки
    skills = _split_list(record.get("skills"))
    if subject is not None:
        known = skill_items(subject)
        unknown_skills = [s for s in skills if s not in known]
        if unknown_skills:
            check.error(f"skills: неизвестные коды навыков {', '.join(unknown_skills)}")
        elif exam_item is not None:
            foreign = [s for s in skills if known[s] and exam_item not in known[s]]
            if foreign:
                check.warn(
                    f"skills: {', '.join(foreign)} обычно не относятся к заданию №{exam_item}"
                )
    if not skills:
        check.warn("skills: навыки не указаны — задача не будет влиять на mastery навыков")

    # файлы к задаче
    asset_paths = []
    for name in _split_list(record.get("assets")):
        path = (base_dir / name).resolve()
        if not path.is_relative_to(base_dir.resolve()):
            # Файлы берутся только из папки с файлом задач: иначе через импорт
            # (например, загруженный на сайт) можно было бы прочитать чужие файлы.
            check.error(f"assets: файл должен лежать рядом с файлом задач: {name}")
        elif not path.is_file():
            check.error(f"assets: файл не найден: {name}")
        elif path.stat().st_size > MAX_ASSET_BYTES:
            check.error(f"assets: файл больше 50 МБ: {name}")
        else:
            asset_paths.append(str(path))

    hints = _parse_hints(record.get("hints"), answer, check)
    tests = _parse_tests(record.get("tests"), subject, check)

    if not check.ok or subject is None or exam_item is None:
        return None
    if source is None or status is None or answer_type is None:
        return None
    return TaskDraft(
        subject=subject,
        exam_item=exam_item,
        statement=statement,
        answer_type=answer_type,
        answer=answer,
        solution=str(record["solution"]).strip() if record.get("solution") else None,
        difficulty=difficulty,
        time_norm_seconds=time_norm_seconds,
        source=source,
        source_ref=source_ref,
        source_version=source_version,
        verification_status=status,
        skills=tuple(dict.fromkeys(skills)),
        asset_paths=tuple(asset_paths),
        content_hash=content_hash(subject, exam_item, statement),
        hints=hints,
        tests=tests,
    )


def build_report(
    path: Path,
    specs: dict[Subject, ExamSpec],
    skill_items: Callable[[Subject], dict[str, tuple[int, ...]]],
    existing_hashes: Callable[[set[str]], set[str]],
    starter_bank: bool = False,
) -> ImportReport:
    """Проверить файл и собрать отчёт. Ничего не записывает.

    starter_bank — файл стартового банка из репозитория: его задачи от ИИ могут быть REVIEWED.
    """
    report = ImportReport(file_name=path.name, file_format=path.suffix.lower().lstrip("."))
    try:
        report.file_format, records = read_records(path)
    except ImportFileError as e:
        report.errors.append(ImportIssue(None, str(e)))
        return report
    report.total = len(records)

    drafts: list[tuple[int, TaskDraft]] = []
    for row, record in enumerate(records, start=1):
        check = _RowChecker(row, report.errors, report.warnings)
        draft = _validate_record(record, check, specs, skill_items, path.parent, starter_bank)
        if draft is not None:
            drafts.append((row, draft))

    in_db = existing_hashes({d.content_hash for _, d in drafts})
    first_seen: dict[str, int] = {}
    for row, draft in drafts:
        if draft.content_hash in in_db:
            report.errors.append(ImportIssue(row, "такая задача уже есть в базе"))
        elif draft.content_hash in first_seen:
            report.errors.append(
                ImportIssue(
                    row, f"повторяет задачу №{first_seen[draft.content_hash]} из этого файла"
                )
            )
        else:
            first_seen[draft.content_hash] = row
            report.accepted.append(draft)
    return report
