"""TutorApp — единая точка входа в CORE для всех интерфейсов (CLI сейчас, Web потом).

Интерфейсы не содержат логики: они вызывают методы TutorApp и показывают результат.
Новые возможности добавляются сюда по фазам roadmap.
"""

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass, replace
from pathlib import Path

from ege_tutor import __version__
from ege_tutor.ai import DisabledSpeechService, make_ai, make_speech
from ege_tutor.config import Settings, load_settings
from ege_tutor.core.clock import SystemClock
from ege_tutor.core.domain import (
    AICall,
    AINote,
    AIStatus,
    Attempt,
    AttemptMode,
    Catalog,
    ChatMessage,
    ChatRole,
    CodeRun,
    DiagnosticItemResult,
    DiagnosticSession,
    DiagnosticState,
    DiagnosticStatus,
    ExamSpec,
    ImportBatch,
    ImportReport,
    MasteryAggregate,
    Mistake,
    MistakeCategory,
    MistakePattern,
    Part2Grade,
    ReviewItem,
    SkillMastery,
    StopReason,
    StudentProfile,
    Subject,
    Task,
    TaskAsset,
    TaskSource,
    Topic,
)
from ege_tutor.core.errors import AppError
from ege_tutor.core.ports import (
    AIService,
    Clock,
    Repository,
    RepositoryError,
    Sandbox,
    SpeechService,
)
from ege_tutor.core.services.assistant import AIHint, AssistantService, GeneratedTask
from ege_tutor.core.services.catalog import load_catalog
from ege_tutor.core.services.code import CodeService
from ege_tutor.core.services.content_import import build_report
from ege_tutor.core.services.diagnostics import DiagnosticsService
from ege_tutor.core.services.mastery import Calibration, MasteryService
from ege_tutor.core.services.practice import AttemptResult, PracticeService, ShownHint
from ege_tutor.core.services.voice import SpeechClip, VoiceService, speakable
from ege_tutor.sandbox import make_sandbox
from ege_tutor.subjects import tutor_for

CURRENT_PHASE = 6
DB_FILE_NAME = "ege.db"
BACKUP_PREFIX = "ege-"
DEFAULT_BACKUPS_KEPT = 14
# Стартовый банк задач (ADR-0016): AI_GENERATED, проверены тестами репозитория.
STARTER_BANK_FILES = ("bank/math_profile.yaml", "bank/informatics.yaml")


@dataclass(frozen=True)
class ExamCountdown:
    subject: Subject
    status: str
    date: dt.date | None
    days_left: int | None  # None, пока дата не утверждена официально


@dataclass(frozen=True)
class AppInfo:
    version: str
    phase: int
    exams: tuple[ExamCountdown, ...]
    storage_ready: bool
    ai_available: bool
    sandbox_available: bool
    task_count: int


@dataclass(frozen=True)
class ImportResult:
    report: ImportReport
    batch: ImportBatch | None  # None — нечего записывать или это был предпросмотр


@dataclass(frozen=True)
class DiagnosticStep:
    """Следующий шаг диагностики: задача для решения или итог."""

    session: DiagnosticSession
    attempt: Attempt | None  # None — диагностика завершена
    task: Task | None


class TutorApp:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        ai: AIService,
        sandbox: Sandbox,
        repository: Repository,
        catalog: Catalog,
        speech: SpeechService | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.ai = ai
        self.sandbox = sandbox
        self.repository = repository
        self.catalog = catalog
        self.practice = PracticeService(
            repository, clock, settings.mastery, tutor_for, self._time_norm
        )
        self.mastery = MasteryService(repository, clock, settings.mastery, catalog)
        self.code = CodeService(repository, clock, sandbox, settings.app.sandbox, self.asset_path)
        self.diagnostics = DiagnosticsService(repository, clock, settings.diagnostics, catalog)
        # ИИ передаётся только помощнику; диагностика (и будущий Exam Mode) его не получают.
        self.assistant = AssistantService(
            repository,
            clock,
            ai,
            settings.app.ai,
            catalog,
            tutor_for,
            sandbox,
            settings.app.sandbox,
            settings.mastery.independence.for_hint_level,
            self.asset_root,
            speech,
        )
        self.voice = VoiceService(
            repository,
            clock,
            speech or DisabledSpeechService(),
            settings.app.speech,
            self.assistant.status,
            settings.data_dir / "speech_cache",
        )

    @classmethod
    def create(
        cls,
        settings: Settings | None = None,
        clock: Clock | None = None,
        repository: Repository | None = None,
        sandbox: Sandbox | None = None,
        ai: AIService | None = None,
        speech: SpeechService | None = None,
    ) -> "TutorApp":
        """Собрать приложение с реализациями по умолчанию для текущей фазы.

        Открывает локальную базу (создаёт и обновляет схему при необходимости)
        и синхронизирует каталог тем из content/.
        """
        from ege_tutor.db.repository import SqlRepository  # адаптер подключается только здесь

        settings = settings or load_settings()
        catalog = load_catalog(settings.content_dir)
        if repository is None:
            repository = SqlRepository.open(settings.data_dir / DB_FILE_NAME)
        repository.sync_catalog(catalog)
        return cls(
            settings=settings,
            clock=clock or SystemClock(),
            ai=ai or make_ai(settings.app.ai),
            speech=speech or make_speech(settings.app.speech, settings.app.ai),
            sandbox=sandbox or make_sandbox(settings.app.sandbox),
            repository=repository,
            catalog=catalog,
        )

    def close(self) -> None:
        self.repository.close()

    # ── резервные копии ─────────────────────────────────────────────────────

    @property
    def backup_dir(self) -> Path:
        return self.settings.data_dir / "backups"

    def backup(self, dest_dir: Path | None = None, keep: int = DEFAULT_BACKUPS_KEPT) -> Path:
        """Сделать копию базы (с проверкой целостности) и оставить только keep последних."""
        if keep < 1:
            raise AppError("нужно хранить хотя бы одну копию")
        folder = dest_dir or self.backup_dir
        stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
        dest = folder / f"{BACKUP_PREFIX}{stamp}.db"
        suffix = 1
        while dest.exists():
            dest = folder / f"{BACKUP_PREFIX}{stamp}-{suffix}.db"
            suffix += 1
        try:
            self.repository.backup_to(dest)
        except RepositoryError as e:
            raise AppError(str(e)) from e
        copies = sorted(
            folder.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: (p.stat().st_mtime, p.name)
        )
        for old in copies[:-keep]:
            old.unlink()
        return dest

    # ── состояние ───────────────────────────────────────────────────────────

    def exam_countdown(self, subject: Subject) -> ExamCountdown:
        exam = self.settings.app.exams[subject]
        days_left = None
        if exam.status == "OFFICIAL" and exam.date is not None:
            days_left = (exam.date - self.clock.today()).days
        return ExamCountdown(subject, exam.status, exam.date, days_left)

    def info(self) -> AppInfo:
        return AppInfo(
            version=__version__,
            phase=CURRENT_PHASE,
            exams=tuple(self.exam_countdown(s) for s in Subject),
            storage_ready=self.repository.is_ready(),
            ai_available=self.assistant.status().available,
            sandbox_available=self.sandbox.is_available,
            task_count=self.repository.count_tasks(),
        )

    # ── профиль ─────────────────────────────────────────────────────────────

    def profile(self) -> StudentProfile:
        return self.repository.get_profile()

    def update_profile(
        self,
        display_name: str | None = None,
        targets: dict[Subject, int] | None = None,
    ) -> StudentProfile:
        current = self.repository.get_profile()
        new_targets = dict(current.targets)
        for subject, score in (targets or {}).items():
            if not 0 <= score <= 100:
                raise AppError(f"цель по предмету должна быть от 0 до 100, получено {score}")
            new_targets[subject] = score
        name = current.display_name if display_name is None else display_name.strip() or None
        if name is not None and len(name) > 100:
            raise AppError("имя не длиннее 100 символов")
        profile = replace(current, display_name=name, targets=new_targets)
        self.repository.save_profile(profile)
        return profile

    # ── каталог ─────────────────────────────────────────────────────────────

    def exam_spec(self, subject: Subject) -> ExamSpec:
        spec = self.repository.get_exam_spec(subject)
        if spec is None:
            raise AppError("структура экзамена не загружена")
        return spec

    def topics(self, subject: Subject) -> list[Topic]:
        return self.repository.list_topics(subject)

    # ── импорт задач ────────────────────────────────────────────────────────

    def _skill_items(self, subject: Subject) -> dict[str, tuple[int, ...]]:
        return {
            skill.code: skill.exam_items
            for topic in self.catalog.topics_of(subject)
            for skill in topic.skills
        }

    def preview_import(self, path: Path, *, starter_bank: bool = False) -> ImportReport:
        """Проверить файл с задачами, ничего не записывая."""
        return build_report(
            path,
            specs=self.catalog.specs,
            skill_items=self._skill_items,
            existing_hashes=self.repository.active_task_hashes,
            starter_bank=starter_bank,
        )

    @property
    def asset_root(self) -> Path:
        """Папка, где лежат файлы к задачам (вне Git)."""
        return self.settings.data_dir / "private_content" / "assets"

    def import_tasks(self, path: Path, *, starter_bank: bool = False) -> ImportResult:
        """Записать задачи без ошибок одной пачкой. Ошибочные остаются в отчёте."""
        report = self.preview_import(path, starter_bank=starter_bank)
        if report.file_error or not report.accepted:
            return ImportResult(report, None)
        batch = self.repository.add_import_batch(
            file_name=report.file_name,
            file_format=report.file_format,
            drafts=report.accepted,
            asset_root=self.asset_root,
            rejected_count=len(report.rejected_rows),
            report=report.to_dict(),
            created_at=self.clock.now(),
        )
        return ImportResult(report, batch)

    def import_batches(self) -> list[ImportBatch]:
        return self.repository.list_import_batches()

    def rollback_import(self, batch_id: int) -> ImportBatch:
        try:
            return self.repository.rollback_import_batch(batch_id, self.clock.now())
        except RepositoryError as e:
            raise AppError(str(e)) from e

    # ── задачи ──────────────────────────────────────────────────────────────

    def tasks(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        source: TaskSource | None = None,
        limit: int = 50,
    ) -> list[Task]:
        return self.repository.list_tasks(subject, exam_item, source, limit)

    def task(self, task_id: int) -> Task:
        task = self.repository.get_task(task_id)
        if task is None:
            raise AppError(f"задача №{task_id} не найдена")
        return task

    def asset_path(self, asset: TaskAsset) -> Path:
        """Где на диске лежит файл задачи."""
        return self.asset_root / asset.stored_path

    # ── решение задач (Phase 2) ─────────────────────────────────────────────

    def _time_norm(self, subject: Subject, exam_item: int) -> int | None:
        spec = self.catalog.specs.get(subject)
        item = spec.item(exam_item) if spec else None
        return item.time_norm_seconds if item else None

    def next_task(self, subject: Subject | None = None, exam_item: int | None = None) -> Task:
        """Какую задачу решать: проверенную, которую решали реже и давнее всего."""
        return self.practice.next_task(subject, exam_item)

    def similar_task(self, task_id: int) -> Task | None:
        return self.practice.similar_task(task_id)

    def start_attempt(self, task_id: int, mode: AttemptMode = AttemptMode.PRACTICE) -> Attempt:
        attempt = self.practice.start(task_id, mode)
        self.mastery.on_attempt_started(attempt, self.task(task_id))
        return attempt

    def next_hint(self, attempt_id: int) -> ShownHint:
        return self.practice.next_hint(attempt_id)

    def submit_answer(self, attempt_id: int, answer: str) -> AttemptResult:
        result = self.practice.submit(attempt_id, answer)
        self.mastery.on_attempt_finished(result.attempt, result.task)
        return result

    def give_up(self, attempt_id: int) -> Attempt:
        attempt = self.practice.give_up(attempt_id)
        self.mastery.on_attempt_finished(attempt, self.task(attempt.task_id))
        return attempt

    def abandon_attempt(self, attempt_id: int) -> Attempt:
        return self.practice.abandon(attempt_id)

    def attempt(self, attempt_id: int) -> Attempt:
        attempt = self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise AppError(f"попытка №{attempt_id} не найдена")
        return attempt

    def shown_hints(self, attempt_id: int) -> list[ShownHint]:
        return self.practice.shown_hints(attempt_id, self.assistant.hint_texts(attempt_id))

    def attempts(self, task_id: int | None = None, limit: int = 50) -> list[Attempt]:
        return self.repository.list_attempts(task_id, limit)

    def review_task(self, task_id: int, answer_is_correct: bool) -> Task:
        return self.practice.review(task_id, answer_is_correct)

    def next_unverified_task(
        self,
        subject: Subject | None = None,
        exam_item: int | None = None,
        exclude: Collection[int] = (),
    ) -> Task | None:
        return self.practice.next_unverified(subject, exam_item, exclude)

    def why_not_practicable(self, task: Task) -> str | None:
        """Почему задачу нельзя решать, или None, если можно."""
        return self.practice.why_not_practicable(task)

    # ── программы на Python (Phase 3) ───────────────────────────────────────

    def run_code(self, task_id: int, code: str, attempt_id: int | None = None) -> CodeRun:
        """Проверить программу на тестах задачи в песочнице и записать запуск."""
        return self.code.run(task_id, code, attempt_id)

    def code_runs(
        self, task_id: int | None = None, attempt_id: int | None = None, limit: int = 20
    ) -> list[CodeRun]:
        return self.code.runs(task_id, attempt_id, limit)

    def code_run(self, run_id: int) -> CodeRun:
        run = self.repository.get_code_run(run_id)
        if run is None:
            raise AppError(f"запуск №{run_id} не найден")
        return run

    # ── mastery, ошибки, повторения (Phase 4) ───────────────────────────────

    def skill_masteries(self, subject: Subject | None = None) -> list[SkillMastery]:
        return self.mastery.skill_masteries(subject)

    def mastery_by_topic(self, subject: Subject) -> list[MasteryAggregate]:
        return self.mastery.by_topic(subject)

    def mastery_by_exam_item(self, subject: Subject) -> list[MasteryAggregate]:
        return self.mastery.by_exam_item(subject)

    def recalculate_mastery(self) -> int:
        """Пересчитать mastery и паттерны ошибок по всей истории попыток."""
        return self.mastery.recalculate_all()

    def calibration(self) -> Calibration:
        return self.mastery.calibration()

    def mistakes(self, skill_code: str | None = None, limit: int = 50) -> list[Mistake]:
        return self.mastery.mistakes(skill_code, limit)

    def attempt_mistakes(self, attempt_id: int) -> list[Mistake]:
        return self.mastery.attempt_mistakes(attempt_id)

    def reclassify_mistake(self, mistake_id: int, category: MistakeCategory) -> Mistake:
        return self.mastery.reclassify(mistake_id, category)

    def mistake_patterns(self, open_only: bool = True) -> list[MistakePattern]:
        return self.mastery.patterns(open_only)

    def review_queue(self, subject: Subject | None = None) -> list[ReviewItem]:
        return self.mastery.review_queue(subject)

    def skill_title(self, skill_code: str) -> str:
        info = self.mastery.skills.get(skill_code)
        return info.title if info else skill_code

    def next_review_task(self, subject: Subject | None = None) -> Task:
        """Задача для повторения: на первый навык очереди, у которого есть проверенные задачи."""
        queue = self.review_queue(subject)
        if not queue:
            raise AppError("повторять пока нечего: очередь повторений пуста")
        for item in queue:
            task = self.practice.task_for_skill(item.skill_code)
            if task is not None:
                return task
        raise AppError("для навыков из очереди нет проверенных задач: добавь задачи и проверь их")

    def start_review(self, subject: Subject | None = None) -> Attempt:
        """Начать повторение (режим REVIEW) по очереди повторений."""
        return self.start_attempt(self.next_review_task(subject).id, AttemptMode.REVIEW)

    # ── стартовый банк и диагностика (Phase 5) ──────────────────────────────

    def starter_bank_paths(self) -> list[Path]:
        return [self.settings.content_dir / name for name in STARTER_BANK_FILES]

    def install_starter_bank(self) -> list[ImportResult]:
        """Загрузить стартовый банк. Уже загруженные задачи пропускаются как дубли."""
        paths = self.starter_bank_paths()
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            raise AppError(f"файлы стартового банка не найдены: {', '.join(missing)}")
        return [self.import_tasks(path, starter_bank=True) for path in paths]

    def diagnostic_task_count(self, subject: Subject) -> int:
        return len(self.diagnostics.eligible_tasks(subject))

    def start_diagnostic(self, subject: Subject) -> DiagnosticSession:
        """Начать диагностику по предмету или продолжить начатую."""
        return self.diagnostics.start(subject)

    def diagnostic_step(self, session_id: int) -> DiagnosticStep:
        """Текущая задача диагностики; если её нет — выбрать следующую или завершить."""
        session = self.diagnostics.session(session_id)
        if session.status != DiagnosticStatus.ACTIVE:
            return DiagnosticStep(session, None, None)
        attempt = self.diagnostics.open_attempt(session_id)
        if attempt is not None:
            return DiagnosticStep(session, attempt, self.task(attempt.task_id))
        choice = self.diagnostics.choose(session_id)
        if choice.task is None:
            assert choice.stop is not None
            return DiagnosticStep(self.diagnostics.finish(session_id, choice.stop), None, None)
        attempt = self.start_attempt(choice.task.id, AttemptMode.DIAGNOSTIC)
        self.diagnostics.link(session_id, attempt.id)
        return DiagnosticStep(session, attempt, choice.task)

    def finish_diagnostic(self, session_id: int) -> DiagnosticSession:
        """Завершить диагностику досрочно: baseline — по тому, что уже решено."""
        session = self.diagnostics.session(session_id)
        if session.status != DiagnosticStatus.ACTIVE:
            raise AppError("эта диагностика уже завершена")
        attempt = self.diagnostics.open_attempt(session_id)
        if attempt is not None:
            self.practice.abandon(attempt.id)
        return self.diagnostics.finish(session_id, StopReason.USER)

    def diagnostic_state(self, session_id: int) -> DiagnosticState:
        return self.diagnostics.state(session_id)

    def diagnostic_session(self, session_id: int) -> DiagnosticSession:
        return self.diagnostics.session(session_id)

    def diagnostic_sessions(
        self, subject: Subject | None = None, limit: int = 20
    ) -> list[DiagnosticSession]:
        return self.diagnostics.sessions(subject, limit)

    def active_diagnostic(self, subject: Subject) -> DiagnosticSession | None:
        return self.diagnostics.active(subject)

    def diagnostic_results(self, session_id: int) -> list[DiagnosticItemResult]:
        return self.diagnostics.results(session_id)

    def diagnostic_session_of_attempt(self, attempt_id: int) -> int | None:
        return self.diagnostics.session_of_attempt(attempt_id)

    # ── ИИ-помощник (Phase 6, ADR-0017) ─────────────────────────────────────

    def ai_status(self) -> AIStatus:
        return self.assistant.status()

    def ai_calls(self, limit: int = 50) -> list[AICall]:
        return self.repository.list_ai_calls(limit)

    def ai_hint_level(self, attempt_id: int) -> int | None:
        """Какой уровень подсказки может сейчас дать ИИ (None — никакой)."""
        attempt = self.attempt(attempt_id)
        if not self.assistant.status().available:
            return None
        return self.assistant.ai_hint_level(attempt, self.task(attempt.task_id))

    def ai_hint(self, attempt_id: int) -> AIHint:
        previous = [h.text for h in self.shown_hints(attempt_id) if h.text]
        return self.assistant.hint(attempt_id, previous)

    def ai_explain(self, attempt_id: int) -> AINote:
        return self.assistant.explain(attempt_id)

    def ai_explanation(self, attempt_id: int) -> AINote | None:
        return self.assistant.explanation(attempt_id)

    def ai_allowed_for(self, attempt_id: int) -> bool:
        """Можно ли в этой попытке пользоваться ИИ (не диагностика, не экзамен)."""
        return self.assistant.can_use_in(self.attempt(attempt_id))

    def ai_classify_mistake(self, mistake_id: int) -> AINote:
        return self.assistant.classify_mistake(mistake_id)

    def ai_mistake_note(self, mistake_id: int) -> AINote | None:
        return self.assistant.mistake_note(mistake_id)

    def ai_grade_part2(self, task_id: int, solution_text: str) -> Part2Grade:
        return self.assistant.grade_part2(task_id, solution_text)

    def part2_grades(self, task_id: int | None = None) -> list[Part2Grade]:
        return self.assistant.part2_grades(task_id)

    def part2_grade(self, grade_id: int) -> Part2Grade:
        return self.assistant.part2_grade(grade_id)

    def ai_generate_similar(self, task_id: int) -> GeneratedTask:
        return self.assistant.generate_similar(task_id)

    def why_cannot_generate(self, task: Task) -> str | None:
        return self.assistant.why_cannot_generate(task)

    # ── разговор с репетитором и голос (Phase 6.5, ADR-0018) ────────────────

    def chat_messages(self, attempt_id: int) -> list[ChatMessage]:
        return self.assistant.chat_messages(attempt_id)

    def can_chat(self, attempt_id: int) -> bool:
        """Можно ли сейчас спросить репетитора в этой попытке."""
        return (
            self.assistant.can_chat(self.attempt(attempt_id)) and self.assistant.status().available
        )

    def ask_tutor(self, attempt_id: int, question: str) -> ChatMessage:
        return self.assistant.ask(attempt_id, question)

    def listen(self, attempt_id: int, pcm: bytes, sample_rate: int) -> str:
        """Распознать вопрос, заданный голосом (текст ученик проверяет и отправляет сам)."""
        return self.voice.listen(attempt_id, pcm, sample_rate)

    def speak_note(self, note_id: int) -> SpeechClip:
        """Озвучить ответ ИИ: подсказку, объяснение или разбор ошибки."""
        note = self.repository.get_ai_note(note_id)
        if note is None:
            raise AppError(f"ответ ИИ №{note_id} не найден")
        return self.voice.speak(
            speakable(note.text), attempt_id=note.attempt_id, task_id=note.task_id
        )

    def speak_chat(self, message_id: int) -> SpeechClip:
        """Озвучить реплику репетитора."""
        message = self.repository.get_chat_message(message_id)
        if message is None or message.role != ChatRole.TUTOR:
            raise AppError(f"реплика №{message_id} не найдена")
        return self.voice.speak(
            message.speech or speakable(message.text), attempt_id=message.attempt_id
        )

    def speak_hint(self, attempt_id: int, level: int) -> SpeechClip:
        """Озвучить уже показанную подсказку попытки."""
        attempt = self.attempt(attempt_id)
        for hint in self.shown_hints(attempt_id):
            if hint.level == level and hint.text:
                return self.voice.speak(
                    speakable(hint.text), attempt_id=attempt.id, task_id=attempt.task_id
                )
        raise AppError("эта подсказка ещё не открыта")

    def speech_clip_path(self, name: str) -> Path | None:
        return self.voice.clip_path(name)
