"""Импорт задач из сохранённой страницы Решу ЕГЭ (ADR-0021).

Ученик решает вариант на сайте, открывает страницу результатов и сохраняет её
(Ctrl+S → «Веб-страница, только HTML»). Здесь эта страница разбирается:

страница → задачи (номер, условие, решение, ответ, подраздел, рисунки и файлы)
         → навыки по таблице content/reshu_ege/subsections.yaml
         → файл задач YAML + скачанные рисунки → обычный конвейер импорта.

Рисунки скачиваются через порт RemoteFiles: CORE сам в интернет не ходит.
Задачи хранятся только в базе на сервере и никогда не попадают в Git.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import yaml

from ege_tutor.core.domain import Subject, TaskSource, VerificationStatus
from ege_tutor.core.ports import RemoteFileError, RemoteFiles

SUBSECTIONS_FILE = Path("reshu_ege") / "subsections.yaml"
SOURCE_VERSION = "Решу ЕГЭ 2027"
TASK_FILE_NAME = "reshu_ege.yaml"
MAX_FILES = 60  # рисунков и файлов на одну страницу
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGE_BYTES = 20 * 1024 * 1024

# Сайт предмета: относительные ссылки на рисунки (/get_file?id=…) считаются от него.
SITES = {
    Subject.MATH_PROFILE: "https://math-ege.sdamgia.ru",
    Subject.INFORMATICS: "https://inf-ege.sdamgia.ru",
}
_SUBJECT_MARKERS = (
    ("математика профильн", Subject.MATH_PROFILE),
    ("математики профильн", Subject.MATH_PROFILE),
    ("информатик", Subject.INFORMATICS),
)
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/zip": ".zip",
}
_HEADER = re.compile(r"Задание\s+(\d+)\s+№\s*(\d+)\s+тип\s+(\d+)", re.IGNORECASE)
_RIGHT_ANSWER = re.compile(r"Правильный ответ:\s*([^\n]+)")
_SOLUTION_ANSWER = re.compile(r"Ответ:\s*([^\n]+)")
_ROW_TITLE = re.compile(r"Задани[ея]\s+(\d+)\.\s*(.+)")
_FRACTION = re.compile(r"дробь: числитель: ([^:]*?), знаменатель: ([^:]*?) конец дроби")
_VOID = {"img", "br", "input", "meta", "link", "hr", "source", "wbr", "col", "area", "base"}
_BLOCK = {"p", "div", "br", "center", "li", "tr", "table", "h1", "h2", "h3", "ul", "ol"}


class ReshuPageError(Exception):
    """Страницу нельзя разобрать. Текст понятен пользователю."""


@dataclass
class ReshuProblem:
    """Одна задача со страницы результатов."""

    position: int
    problem_id: str
    exam_item: int
    statement: str = ""
    solution: str | None = None
    answer: str | None = None
    subsection: str | None = None
    files: list[str] = field(default_factory=list)  # абсолютные ссылки на рисунки и файлы


@dataclass
class ReshuPage:
    subject: Subject
    problems: list[ReshuProblem]


@dataclass
class ReshuConversion:
    """Итог перевода страницы в файл задач."""

    task_file: Path
    subject: Subject
    problems: int
    files_downloaded: int
    file_errors: list[str]


def clean_text(text: str) -> str:
    """Убрать мягкие переносы и узкие пробелы, схлопнуть пробелы в строках."""
    text = text.replace("\xad", "").replace(" ", " ").replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def formula_text(alt: str) -> str:
    """Подпись формулы (alt) в читаемый вид: простые дроби — как (a)/(b)."""
    text = clean_text(alt)
    while True:
        new = _FRACTION.sub(lambda m: f"({m.group(1).strip()})/({m.group(2).strip()})", text)
        if new == text:
            return text
        text = new


class _Capture:
    """Сбор текста одного блока (условие или решение)."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.links: list[str] = []

    def text(self) -> str:
        return clean_text("".join(self.parts))


class _ResultsParser(HTMLParser):
    """Разбор страницы результатов Решу ЕГЭ потоком, без сторонних библиотек."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.subject_name = ""
        self.problems: list[ReshuProblem] = []
        self.row_titles: dict[str, str] = {}  # № задачи → «Задания 1. Планиметрия. …»
        self.variant_page = False
        self._in_title = False
        self._in_subject_name = False
        self._div_depth = 0
        self._problem: ReshuProblem | None = None
        self._problem_depth = 0
        self._problem_text: list[str] = []
        self._bold: list[str] | None = None
        self._capture: _Capture | None = None
        self._capture_depth = 0
        self._captures: list[_Capture] = []
        self._row_id: str | None = None
        self._row_title: str | None = None

    # ── теги ──

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = set(a.get("class", "").split())
        if tag == "title":
            self._in_title = True
        if "prob_maindiv" in classes:
            self.variant_page = True
        if "Header-SubjectName" in classes:
            self._in_subject_name = True
        if tag == "tr":
            self._row_id, self._row_title = None, None
        if tag == "td" and a.get("title", "").startswith("Задани"):
            self._row_title = a["title"]
        if tag == "a" and self._capture is None:
            pid = _problem_id(a.get("href", ""))
            if pid and self._problem is None:
                self._row_id = pid
            name = a.get("name", "")
            if name.startswith("prob") and name[4:].isdigit():
                self._start_problem(int(name[4:]))
        if tag == "div":
            self._div_depth += 1
            if self._problem is not None and self._capture is None and "pbody" in classes:
                self._capture = _Capture()
                self._capture_depth = self._div_depth
                return
        if tag == "b" and self._problem is not None and self._capture is None:
            self._bold = []
        if self._capture is not None:
            self._capture_tag(tag, a, classes)
        elif self._problem is not None and tag in _BLOCK:
            self._problem_text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "tr" and self._row_id and self._row_title:
            self.row_titles.setdefault(self._row_id, self._row_title)
        if tag == "b" and self._bold is not None:
            self._header(clean_text("".join(self._bold)))
            self._bold = None
        if tag == "div":
            self._in_subject_name = False
            if self._capture is not None and self._div_depth == self._capture_depth:
                self._captures.append(self._capture)
                self._capture = None
            if self._problem is not None and self._div_depth == self._problem_depth:
                self._finish_problem()
            self._div_depth -= 1
        if self._capture is not None and tag in {"p", "li", "tr"}:
            self._capture.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_subject_name:
            self.subject_name += data
        if self._capture is not None:
            self._capture.parts.append(data)
        elif self._problem is not None:
            self._problem_text.append(data)
            if self._bold is not None:
                self._bold.append(data)

    # ── задача ──

    def _start_problem(self, position: int) -> None:
        if self._problem is not None:
            self._finish_problem()
        self._problem = ReshuProblem(position=position, problem_id="", exam_item=0)
        self._problem_depth = self._div_depth  # задача — это div, внутри которого якорь
        self._problem_text, self._captures, self._capture = [], [], None

    def _header(self, text: str) -> None:
        match = _HEADER.search(text)
        if self._problem is not None and match and not self._problem.problem_id:
            self._problem.problem_id = match.group(2)
            self._problem.exam_item = int(match.group(3))

    def _capture_tag(self, tag: str, a: dict[str, str], classes: set[str]) -> None:
        capture = self._capture
        assert capture is not None
        if tag in _BLOCK:
            capture.parts.append("\n")
        if tag == "img":
            if "tex" in classes:
                capture.parts.append(" " + formula_text(a.get("alt", "")) + " ")
            elif a.get("src"):
                capture.links.append(a["src"])
        if tag == "a" and "get_file" in a.get("href", ""):
            capture.links.append(a["href"])

    def _finish_problem(self) -> None:
        problem = self._problem
        self._problem = None
        if problem is None or not problem.problem_id or not self._captures:
            return
        statement = self._captures[0]
        problem.statement = statement.text()
        links = list(statement.links)
        if len(self._captures) > 1:
            solution = self._captures[1]
            problem.solution = solution.text() or None
            links += solution.links
        problem.files = links
        text = clean_text("".join(self._problem_text))
        match = _RIGHT_ANSWER.search(text)
        if match:
            problem.answer = _answer(match.group(1))
        elif problem.solution:
            found = _SOLUTION_ANSWER.findall(problem.solution)
            problem.answer = _answer(found[-1]) if found else None
        self.problems.append(problem)


def _problem_id(href: str) -> str | None:
    parts = urlsplit(href)
    if not parts.path.endswith("/problem"):
        return None
    values = parse_qs(parts.query).get("id")
    return values[0] if values and values[0].isdigit() else None


def _answer(raw: str) -> str | None:
    text = clean_text(raw).rstrip(".").strip()
    return text or None


def detect_subject(title: str, subject_name: str) -> Subject:
    text = clean_text(f"{title} {subject_name}").lower()
    if "базов" in text:
        raise ReshuPageError("это страница базовой математики, а мы готовимся к профильной")
    for marker, subject in _SUBJECT_MARKERS:
        if marker in text:
            return subject
    raise ReshuPageError(
        "не понятно, какой это предмет: нужна страница профильной математики или информатики"
    )


def parse_results_page(text: str) -> ReshuPage:
    """Разобрать страницу результатов варианта Решу ЕГЭ."""
    parser = _ResultsParser()
    parser.feed(text)
    parser.close()
    parser._finish_problem()
    if not parser.problems:
        if parser.variant_page:
            raise ReshuPageError(
                "это страница самого варианта, на ней нет ответов и решений. "
                "Нажми «Завершить работу, свериться с ответами, увидеть решения» "
                "и сохрани страницу результатов"
            )
        raise ReshuPageError("на странице не найдено задач Решу ЕГЭ с решениями")
    subject = detect_subject(parser.title, parser.subject_name)
    site = SITES[subject]
    for problem in parser.problems:
        row = parser.row_titles.get(problem.problem_id)
        match = _ROW_TITLE.match(clean_text(row)) if row else None
        problem.subsection = match.group(2) if match else None
        problem.files = list(dict.fromkeys(urljoin(site + "/", link) for link in problem.files))
    return ReshuPage(subject, parser.problems)


# ── подразделы → навыки ─────────────────────────────────────────────────────


def _norm(text: str) -> str:
    text = clean_text(text).lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@dataclass(frozen=True)
class SubsectionMap:
    """Таблица «подраздел Решу ЕГЭ → навыки» для одного предмета."""

    items: dict[int, dict[str, tuple[str, ...]]]

    def skills(self, exam_item: int, subsection: str | None) -> tuple[str, ...]:
        """Навыки задачи. Подраздел ищется по названию или его началу, иначе — default."""
        table = self.items.get(exam_item, {})
        if subsection:
            # «Задания 1. Планиметрия. Трапеция»: подраздел — последняя часть, но
            # в названии самого подраздела тоже бывает точка, поэтому пробуем все хвосты.
            pieces = subsection.split(". ")
            for start in range(len(pieces)):
                name = _norm(". ".join(pieces[start:]))
                best = max(
                    (key for key in table if key != "default" and name.startswith(key)),
                    key=len,
                    default=None,
                )
                if best:
                    return table[best]
        return table.get("default", ())

    def all_skills(self) -> set[str]:
        return {s for table in self.items.values() for skills in table.values() for s in skills}


def load_subsection_maps(content_dir: Path) -> dict[Subject, SubsectionMap]:
    path = content_dir / SUBSECTIONS_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    maps: dict[Subject, SubsectionMap] = {}
    for subject_name, items in data.items():
        subject = Subject(subject_name)
        table: dict[int, dict[str, tuple[str, ...]]] = {}
        for item, entries in (items or {}).items():
            table[int(item)] = {
                (key if key == "default" else _norm(key)): tuple(skills)
                for key, skills in entries.items()
            }
        maps[subject] = SubsectionMap(table)
    return maps


# ── страница → файл задач ───────────────────────────────────────────────────


def _file_name(url: str, mime: str, index: int) -> str:
    file_id = parse_qs(urlsplit(url).query).get("id", [""])[0]
    stem = f"reshu_{file_id}" if file_id.isdigit() else f"reshu_file_{index}"
    suffix = _EXTENSIONS.get(mime) or Path(urlsplit(url).path).suffix.lower() or ".bin"
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ".bin"
    return stem + suffix


def _source_ref(problem: ReshuProblem) -> str:
    ref = f"Решу ЕГЭ, задача №{problem.problem_id}"
    if problem.subsection:
        ref += f", подраздел «{problem.subsection}»"
    return ref


def convert_page(
    page_path: Path,
    maps: dict[Subject, SubsectionMap],
    remote: RemoteFiles,
    extended_items: dict[Subject, set[int]],
) -> ReshuConversion:
    """Перевести сохранённую страницу в файл задач YAML рядом с ней.

    Рисунки и файлы к задачам скачиваются в ту же папку. Если что-то не скачалось,
    задача всё равно попадёт в отчёт, а ошибка — в список file_errors.
    """
    raw = page_path.read_bytes()
    if len(raw) > MAX_PAGE_BYTES:
        raise ReshuPageError("страница больше 20 МБ — это точно сохранённый вариант?")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")
    page = parse_results_page(text)
    mapping = maps.get(page.subject, SubsectionMap({}))
    folder = page_path.parent

    downloaded: dict[str, str] = {}
    errors: list[str] = []
    tasks = []
    for problem in page.problems:
        assets = []
        for url in problem.files:
            if url in downloaded:
                assets.append(downloaded[url])
                continue
            if len(downloaded) >= MAX_FILES:
                errors.append(f"задача №{problem.problem_id}: больше {MAX_FILES} файлов, {url}")
                continue
            try:
                data, mime = remote.fetch(url, MAX_FILE_BYTES)
            except RemoteFileError as e:
                errors.append(f"задача №{problem.problem_id}: {e}")
                continue
            name = _file_name(url, mime, len(downloaded) + 1)
            (folder / name).write_bytes(data)
            downloaded[url] = name
            assets.append(name)
        extended = problem.exam_item in extended_items.get(page.subject, set())
        has_answer = bool(problem.answer)
        record: dict = {
            "exam_item": problem.exam_item,
            "statement": problem.statement,
            "answer_type": "EXTENDED" if extended else "NUMBER",
            "skills": list(mapping.skills(problem.exam_item, problem.subsection)),
            "source_ref": _source_ref(problem),
        }
        if problem.answer:
            record["answer"] = problem.answer
            if not extended:
                record["answer_type"] = _answer_type(problem.answer)
        if problem.solution:
            record["solution"] = problem.solution
        if assets:
            record["assets"] = assets
        # Ответ взят с сайта: задачу можно решать сразу. Без ответа — на проверку.
        if has_answer or (extended and problem.solution):
            record["verification_status"] = VerificationStatus.REVIEWED.value
        tasks.append(record)

    task_file = folder / TASK_FILE_NAME
    document = {
        "defaults": {
            "subject": page.subject.value,
            "source": TaskSource.USER_MATERIAL.value,
            "source_version": SOURCE_VERSION,
            "verification_status": VerificationStatus.UNVERIFIED.value,
        },
        "tasks": tasks,
    }
    task_file.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return ReshuConversion(task_file, page.subject, len(tasks), len(downloaded), errors)


def _is_number(text: str) -> bool:
    try:
        float(text.replace(",", "."))
    except ValueError:
        return False
    return True


def _answer_type(answer: str) -> str:
    """Тип краткого ответа: число, несколько чисел через пробел или строка."""
    parts = answer.split()
    if len(parts) == 1 and _is_number(answer):
        return "NUMBER"
    if len(parts) > 1 and all(_is_number(p) for p in parts):
        return "SEQUENCE"
    return "TEXT"
