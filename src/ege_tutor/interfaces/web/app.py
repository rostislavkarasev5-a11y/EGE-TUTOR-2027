"""Сайт на FastAPI (ADR-0013). Только ввод/вывод: вся логика — в TutorApp, как и у CLI.

Страницы собираются на сервере из шаблонов Jinja2. Вход — пароль владельца,
сессия — подписанная cookie, все формы защищены CSRF-токеном.
"""

import datetime as dt
import hmac
import secrets
import threading
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from ege_tutor import __version__
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    AI_LABEL,
    AI_PURPOSE_NAMES,
    CODE_VERDICT_LABELS,
    ITEM_BASIS_NAMES,
    MISTAKE_CATEGORY_NAMES,
    SOURCE_LABELS,
    STOP_REASON_NAMES,
    AnswerType,
    AttemptStatus,
    CodeVerdict,
    DiagnosticStatus,
    ImportBatchStatus,
    ItemBasis,
    MistakeCategory,
    ReviewReason,
    Subject,
    Task,
    TaskSource,
    Verdict,
    VerificationStatus,
)
from ege_tutor.interfaces.web import uploads
from ege_tutor.interfaces.web.auth import LoginThrottle, PasswordStore, load_secret_key, web_dir

HERE = Path(__file__).resolve().parent
SESSION_DAYS = 30

SUBJECT_NAMES = {
    Subject.MATH_PROFILE: "Математика (профиль)",
    Subject.INFORMATICS: "Информатика",
}
STATUS_NAMES = {
    VerificationStatus.UNVERIFIED: "не проверена",
    VerificationStatus.AUTO_CHECKED: "проверена автоматически",
    VerificationStatus.REVIEWED: "проверена",
    VerificationStatus.DISPUTED: "спорная",
    VerificationStatus.REJECTED: "отклонена",
}
VERDICT_NAMES = {
    Verdict.CORRECT: "верно",
    Verdict.WRONG: "неверно",
    Verdict.WRONG_FORMAT: "неверный формат",
}
ATTEMPT_STATUS_NAMES = {
    AttemptStatus.IN_PROGRESS: "решается",
    AttemptStatus.ANSWERED: "ответ дан",
    AttemptStatus.GAVE_UP: "сдался",
    AttemptStatus.ABANDONED: "брошена",
}
REVIEW_REASON_NAMES = {
    ReviewReason.FORGETTING: "пора повторить",
    ReviewReason.MISTAKES: "частая ошибка",
}
HINT_NAMES = {
    1: "небольшая подсказка",
    2: "конкретная подсказка",
    3: "подробное объяснение",
    4: "полное решение",
}

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


# Самая длинная запись вопроса: 30 секунд 16-битного звука с частотой 48 кГц.
MAX_RECORDING_BYTES = 30 * 48_000 * 2


class LockedTutor:
    """TutorApp, к которому запросы обращаются по очереди.

    Сайт обрабатывает запросы в нескольких потоках, а пользователь один: очередь
    проще и надёжнее, чем параллельная запись в SQLite.
    """

    def __init__(self, tutor: TutorApp) -> None:
        self._tutor = tutor
        self._lock = threading.RLock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._tutor, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attr(*args, **kwargs)

        return call


class _LoginRequired(Exception):
    def __init__(self, next_path: str) -> None:
        self.next_path = next_path


class _BadCsrf(Exception):
    pass


# ── вспомогательное для шаблонов ────────────────────────────────────────────


def minutes(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def display_answer(task: Task) -> str:
    if task.answer is None:
        return "—"
    if task.answer_type == AnswerType.NUMBER:
        return task.answer.replace(".", ",")  # как на бланке ЕГЭ
    return task.answer


def utc_time(value: dt.datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") + " UTC" if value else "—"


def _safe_next(path: str | None) -> str:
    """Куда вернуться после входа: только страница этого же сайта."""
    if path and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/"


def _parse_subject(text: str | None) -> Subject | None:
    if not text:
        return None
    try:
        return Subject.parse(text)
    except ValueError:
        return None


def _parse_int(text: str | None) -> int | None:
    try:
        return int(text) if text not in (None, "") else None
    except ValueError:
        return None


# ── приложение ──────────────────────────────────────────────────────────────


def create_app(
    tutor: TutorApp,
    *,
    secure_cookies: bool = True,
    password_store: PasswordStore | None = None,
    throttle: LoginThrottle | None = None,
) -> FastAPI:
    """Собрать сайт над готовым TutorApp."""
    data_dir = tutor.settings.data_dir
    passwords = password_store or PasswordStore(web_dir(data_dir) / "password.argon2")
    login_throttle = throttle or LoginThrottle()
    upload_root = web_dir(data_dir) / "uploads"
    core = LockedTutor(tutor)

    app = FastAPI(title="EGE-TUTOR-2027", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=load_secret_key(data_dir),
        session_cookie="ege_session",
        max_age=SESSION_DAYS * 24 * 60 * 60,
        same_site="lax",
        https_only=secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(
        SUBJECT_NAMES=SUBJECT_NAMES,
        STATUS_NAMES=STATUS_NAMES,
        VERDICT_NAMES=VERDICT_NAMES,
        ATTEMPT_STATUS_NAMES=ATTEMPT_STATUS_NAMES,
        HINT_NAMES=HINT_NAMES,
        SOURCE_LABELS=SOURCE_LABELS,
        AI_SOURCE=TaskSource.AI_GENERATED,
        Subject=Subject,
        TaskSource=TaskSource,
        ImportBatchStatus=ImportBatchStatus,
        AttemptStatus=AttemptStatus,
        CODE_VERDICT_LABELS=CODE_VERDICT_LABELS,
        CodeVerdict=CodeVerdict,
        MistakeCategory=MistakeCategory,
        MISTAKE_CATEGORY_NAMES=MISTAKE_CATEGORY_NAMES,
        REVIEW_REASON_NAMES=REVIEW_REASON_NAMES,
        ITEM_BASIS_NAMES=ITEM_BASIS_NAMES,
        STOP_REASON_NAMES=STOP_REASON_NAMES,
        ItemBasis=ItemBasis,
        DiagnosticStatus=DiagnosticStatus,
        AI_LABEL=AI_LABEL,
        AI_PURPOSE_NAMES=AI_PURPOSE_NAMES,
        skill_title=tutor.skill_title,
        time_limit=f"{tutor.settings.app.sandbox.time_limit_seconds:g}",
        memory_limit=tutor.settings.app.sandbox.memory_limit_mb,
        speech_max_seconds=tutor.settings.app.speech.max_recording_seconds,
        version=__version__,
    )
    templates.env.filters.update(minutes=minutes, display_answer=display_answer, utc_time=utc_time)

    # ── сессия, вход, CSRF ──

    def csrf_token(request: Request) -> str:
        token = request.session.get("csrf")
        if not token:
            token = secrets.token_urlsafe(32)
            request.session["csrf"] = token
        return token

    def flash(request: Request, message: str, kind: str = "info") -> None:
        request.session.setdefault("flash", []).append([kind, message])

    def render(request: Request, name: str, status_code: int = 200, **context: Any):
        messages = request.session.pop("flash", [])
        return templates.TemplateResponse(
            request,
            name,
            {
                "csrf": csrf_token(request),
                "messages": messages,
                "logged_in": is_logged_in(request),
                **context,
            },
            status_code=status_code,
        )

    def is_logged_in(request: Request) -> bool:
        fingerprint = passwords.fingerprint()
        return (
            request.session.get("user") == "owner"
            and bool(fingerprint)
            and request.session.get("pw") == fingerprint
        )

    def require_login(request: Request) -> None:
        if not is_logged_in(request):
            target = request.url.path
            if request.url.query:
                target += "?" + request.url.query
            raise _LoginRequired(target)

    async def check_csrf(request: Request) -> None:
        form = await request.form()
        sent = str(form.get("csrf", ""))
        expected = request.session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            raise _BadCsrf

    def redirect(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    @app.exception_handler(_LoginRequired)
    async def _to_login(_request: Request, exc: _LoginRequired):
        return redirect("/login?next=" + quote(exc.next_path, safe="/"))

    @app.exception_handler(_BadCsrf)
    async def _bad_csrf(request: Request, _exc: _BadCsrf):
        return render(
            request,
            "message.html",
            status_code=400,
            title="Форма устарела",
            text="Страница была открыта слишком давно. Вернись назад, обнови её и повтори.",
        )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if secure_cookies:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.url.path not in ("/healthz",) and not request.url.path.startswith("/static"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz")
    def healthz():
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str | None = None):
        if is_logged_in(request):
            return redirect(_safe_next(next))
        return render(
            request,
            "login.html",
            next=_safe_next(next),
            password_set=passwords.is_set(),
        )

    @app.post("/login")
    async def login(
        request: Request,
        password: Annotated[str, Form()] = "",
        next: Annotated[str, Form()] = "/",
    ):
        await check_csrf(request)
        client = request.client.host if request.client else "unknown"
        wait = login_throttle.seconds_locked(client)
        if wait:
            return render(
                request,
                "login.html",
                status_code=429,
                next=_safe_next(next),
                password_set=passwords.is_set(),
                error=f"Слишком много неверных попыток. Подожди {wait // 60 + 1} мин.",
            )
        if not passwords.verify(password):
            login_throttle.failure(client)
            return render(
                request,
                "login.html",
                status_code=401,
                next=_safe_next(next),
                password_set=passwords.is_set(),
                error="Неверный пароль.",
            )
        login_throttle.success(client)
        request.session.clear()  # новая сессия после входа
        request.session["user"] = "owner"
        request.session["pw"] = passwords.fingerprint()
        return redirect(_safe_next(next))

    @app.post("/logout")
    async def logout(request: Request):
        await check_csrf(request)
        request.session.clear()
        return redirect("/login")

    # ── главная ──

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        require_login(request)
        return render(
            request,
            "home.html",
            info=core.info(),
            profile=core.profile(),
            has_unverified=core.next_unverified_task() is not None,
            queue=core.review_queue(),
        )

    # ── прогресс, ошибки, повторение (Phase 4) ──

    @app.get("/progress", response_class=HTMLResponse)
    def progress_page(request: Request, subject: str | None = None):
        require_login(request)
        chosen = _parse_subject(subject) or Subject.MATH_PROFILE
        items = core.mastery_by_exam_item(chosen)
        skills = sorted(core.skill_masteries(chosen), key=lambda m: (m.value, m.skill_code))
        return render(
            request,
            "progress.html",
            subject=chosen,
            items=items,
            any_studied=any(a.value is not None for a in items),
            skills=skills,
            calibration=core.calibration(),
        )

    @app.get("/mistakes", response_class=HTMLResponse)
    def mistakes_page(request: Request):
        require_login(request)
        return render(
            request,
            "mistakes.html",
            patterns=core.mistake_patterns(),
            mistakes=core.mistakes(limit=50),
        )

    @app.post("/mistakes/{mistake_id}")
    async def reclassify_mistake(
        request: Request,
        mistake_id: int,
        category: Annotated[str, Form()] = "",
        back: Annotated[str, Form()] = "/mistakes",
    ):
        require_login(request)
        await check_csrf(request)
        try:
            fixed = core.reclassify_mistake(mistake_id, MistakeCategory(category))
        except ValueError:
            flash(request, "неизвестная причина ошибки", "error")
            return redirect(_safe_next(back))
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(_safe_next(back))
        flash(request, f"Причина ошибки уточнена: {fixed.category_name}.", "success")
        return redirect(_safe_next(back))

    @app.post("/repeat")
    async def repeat(request: Request):
        require_login(request)
        await check_csrf(request)
        try:
            attempt = core.start_review()
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/")
        return redirect(f"/attempts/{attempt.id}")

    # ── стартовый банк и диагностика (Phase 5) ──

    @app.get("/diagnostics", response_class=HTMLResponse)
    def diagnostics_page(request: Request):
        require_login(request)
        subjects = [
            {
                "subject": s,
                "tasks": core.diagnostic_task_count(s),
                "active": core.active_diagnostic(s),
            }
            for s in Subject
        ]
        budget = tutor.settings.diagnostics.budget
        return render(
            request,
            "diagnostics.html",
            subjects=subjects,
            sessions=core.diagnostic_sessions(),
            max_tasks=budget.max_tasks_per_subject,
            max_minutes=budget.max_minutes_per_subject,
        )

    @app.post("/bank")
    async def install_bank(request: Request):
        require_login(request)
        await check_csrf(request)
        try:
            results = await run_in_threadpool(core.install_starter_bank)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/diagnostics")
        added = sum(len(r.report.accepted) for r in results if r.batch is not None)
        flash(request, f"Стартовый банк загружен: добавлено задач {added}.", "success")
        return redirect("/diagnostics")

    @app.post("/diagnostics/start")
    async def start_diagnostic(request: Request, subject: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        chosen = _parse_subject(subject)
        if chosen is None:
            flash(request, "выбери предмет", "error")
            return redirect("/diagnostics")
        try:
            session = core.start_diagnostic(chosen)
            return after_diagnostic_answer(session.id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/diagnostics")

    @app.get("/diagnostics/{session_id}", response_class=HTMLResponse)
    def diagnostic_page(request: Request, session_id: int):
        require_login(request)
        try:
            state = core.diagnostic_state(session_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/diagnostics")
        return render(request, "diagnostic.html", state=state)

    @app.post("/diagnostics/{session_id}/continue")
    async def continue_diagnostic(request: Request, session_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            return after_diagnostic_answer(session_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/diagnostics/{session_id}")

    @app.post("/diagnostics/{session_id}/finish")
    async def finish_diagnostic(request: Request, session_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            core.finish_diagnostic(session_id)
        except AppError as e:
            flash(request, str(e), "error")
        return redirect(f"/diagnostics/{session_id}")

    # ── задачи ──

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks_page(
        request: Request,
        subject: str | None = None,
        item: str | None = None,
        source: str | None = None,
    ):
        require_login(request)
        parsed_source = TaskSource(source) if source in set(TaskSource) else None
        found = core.tasks(_parse_subject(subject), _parse_int(item), parsed_source, limit=500)
        return render(
            request,
            "tasks.html",
            tasks=found,
            subject=subject or "",
            item=item or "",
            source=source or "",
        )

    def load_task(request: Request, task_id: int) -> Task | None:
        try:
            return core.task(task_id)
        except AppError as e:
            flash(request, str(e), "error")
            return None

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_page(request: Request, task_id: int, answer: bool = False):
        require_login(request)
        task = load_task(request, task_id)
        if task is None:
            return redirect("/tasks")
        return render(
            request,
            "task.html",
            task=task,
            show_answer=answer,
            reason=core.why_not_practicable(task),
            ai=core.ai_status(),
            generate_reason=core.why_cannot_generate(task),
            grades=core.part2_grades(task.id),
        )

    @app.get("/tasks/{task_id}/files/{index}")
    def task_file(request: Request, task_id: int, index: int):
        require_login(request)
        task = load_task(request, task_id)
        if task is None or not 0 <= index < len(task.assets):
            return redirect("/tasks")
        asset = task.assets[index]
        path = core.asset_path(asset).resolve()
        if not path.is_relative_to(core.asset_root.resolve()) or not path.is_file():
            flash(request, "файл задачи не найден на диске", "error")
            return redirect(f"/tasks/{task_id}")
        return FileResponse(path, filename=asset.file_name)

    # ── решение ──

    def start_and_open(request: Request, task_id: int):
        try:
            attempt = core.start_attempt(task_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/tasks/{task_id}")
        return redirect(f"/attempts/{attempt.id}")

    @app.post("/solve")
    async def solve_next(
        request: Request,
        subject: Annotated[str, Form()] = "",
        item: Annotated[str, Form()] = "",
    ):
        require_login(request)
        await check_csrf(request)
        request.session["solve_filter"] = [subject, item]
        try:
            task = core.next_task(_parse_subject(subject), _parse_int(item))
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/")
        return start_and_open(request, task.id)

    @app.post("/tasks/{task_id}/start")
    async def solve_task(request: Request, task_id: int):
        require_login(request)
        await check_csrf(request)
        return start_and_open(request, task_id)

    @app.get("/attempts/{attempt_id}", response_class=HTMLResponse)
    def attempt_page(request: Request, attempt_id: int, reveal: bool = False):
        require_login(request)
        try:
            attempt = core.attempt(attempt_id)
            task = core.task(attempt.task_id)
            hints = core.shown_hints(attempt_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/")
        session_id = core.diagnostic_session_of_attempt(attempt_id)
        if session_id is not None and attempt.status != AttemptStatus.IN_PROGRESS:
            # ответы диагностики не показываются по одному: итог — на странице диагностики
            return redirect(f"/diagnostics/{session_id}")
        notes = request.session.get("result_notes", {})
        subject, item = request.session.get("solve_filter", ["", ""])
        runs = []
        code_enabled = task.subject == Subject.INFORMATICS
        if code_enabled:
            runs = core.code_runs(task.id, attempt_id, limit=5)
        mistakes = core.attempt_mistakes(attempt_id)
        ai = core.ai_status()
        ai_allowed = session_id is None and core.ai_allowed_for(attempt_id)
        chat = core.chat_messages(attempt_id) if ai_allowed else []
        speak = request.session.pop("speak_next", None)
        return render(
            request,
            "attempt.html",
            ai=ai,
            ai_allowed=ai_allowed,
            chat=chat,
            chat_enabled=ai_allowed and ai.available and core.can_chat(attempt_id),
            speech_on=ai_allowed and ai.speech_available,
            autoplay_url=speak if isinstance(speak, str) and ai_allowed else None,
            ai_hint_level=core.ai_hint_level(attempt_id) if ai_allowed else None,
            ai_explanation=core.ai_explanation(attempt_id) if ai_allowed else None,
            ai_mistake=core.ai_mistake_note(mistakes[0].id) if ai_allowed and mistakes else None,
            code_enabled=code_enabled,
            sandbox_ready=code_enabled and core.sandbox.is_available,
            runs=runs,
            last_code=runs[0].code if runs else "",
            mistakes=mistakes,
            attempt=attempt,
            task=task,
            hints=hints,
            explanation=notes.get(str(attempt_id), ""),
            reveal=reveal or attempt.status == AttemptStatus.GAVE_UP or attempt.correct,
            started_iso=attempt.started_at.isoformat(),
            filter_subject=subject,
            filter_item=item,
            diagnostic=core.diagnostic_state(session_id) if session_id is not None else None,
        )

    def after_diagnostic_answer(session_id: int):
        """После ответа в диагностике — сразу следующая задача или итог."""
        step = core.diagnostic_step(session_id)
        if step.attempt is not None:
            return redirect(f"/attempts/{step.attempt.id}")
        return redirect(f"/diagnostics/{session_id}")

    @app.post("/attempts/{attempt_id}/answer")
    async def submit_answer(request: Request, attempt_id: int, answer: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        try:
            result = core.submit_answer(attempt_id, answer)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/attempts/{attempt_id}")
        session_id = core.diagnostic_session_of_attempt(attempt_id)
        if session_id is not None:
            return after_diagnostic_answer(session_id)
        notes = request.session.get("result_notes", {})
        notes = dict(list(notes.items())[-9:])  # храним пояснения к последним попыткам
        notes[str(attempt_id)] = result.check.explanation
        request.session["result_notes"] = notes
        return redirect(f"/attempts/{attempt_id}")

    @app.post("/attempts/{attempt_id}/run")
    async def run_code(request: Request, attempt_id: int, code: Annotated[str, Form()] = ""):
        """Запустить программу к задаче. Может занять несколько секунд — не держим сервер."""
        require_login(request)
        await check_csrf(request)
        try:
            attempt = core.attempt(attempt_id)
            await run_in_threadpool(core.run_code, attempt.task_id, code, attempt_id)
        except AppError as e:
            flash(request, str(e), "error")
        return redirect(f"/attempts/{attempt_id}#code")

    @app.post("/attempts/{attempt_id}/hint")
    async def hint(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            core.next_hint(attempt_id)
        except AppError as e:
            flash(request, str(e), "warning")
        return redirect(f"/attempts/{attempt_id}#hints")

    # ── ИИ-помощник (Phase 6) ──
    # Ответ ИИ может идти до минуты, поэтому вызов — в отдельном потоке, а не в цикле сервера.

    @app.post("/attempts/{attempt_id}/ai-hint")
    async def ai_hint(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            made = await run_in_threadpool(core.ai_hint, attempt_id)
            request.session["speak_next"] = f"/speech/hint/{attempt_id}/{made.level}"
        except AppError as e:
            flash(request, str(e), "warning")
        return redirect(f"/attempts/{attempt_id}#hints")

    @app.post("/attempts/{attempt_id}/explain")
    async def ai_explain(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            note = await run_in_threadpool(core.ai_explain, attempt_id)
            request.session["speak_next"] = f"/speech/note/{note.id}"
        except AppError as e:
            flash(request, str(e), "warning")
        return redirect(f"/attempts/{attempt_id}#ai")

    # ── разговор с репетитором и голос (Phase 6.5, ADR-0018) ──

    @app.post("/attempts/{attempt_id}/ask")
    async def ask_tutor(request: Request, attempt_id: int, question: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        try:
            reply = await run_in_threadpool(core.ask_tutor, attempt_id, question)
            request.session["speak_next"] = f"/speech/chat/{reply.id}"
        except AppError as e:
            flash(request, str(e), "warning")
        return redirect(f"/attempts/{attempt_id}#tutor")

    @app.post("/attempts/{attempt_id}/listen")
    async def listen(request: Request, attempt_id: int):
        """Вопрос голосом: браузер присылает запись (16-битный PCM), в ответ — текст."""
        require_login(request)
        await check_csrf(request)
        form = await request.form()
        audio = form.get("audio")
        rate = str(form.get("rate", ""))
        if audio is None or isinstance(audio, str) or not rate.isdigit():
            return JSONResponse({"error": "запись не пришла"}, status_code=400)
        pcm = await audio.read(MAX_RECORDING_BYTES + 1)
        if len(pcm) > MAX_RECORDING_BYTES:
            return JSONResponse({"error": "запись слишком длинная"}, status_code=400)
        try:
            text = await run_in_threadpool(core.listen, attempt_id, pcm, int(rate))
        except AppError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"text": text})

    async def speech_reply(request: Request, make: Any, *args: int) -> JSONResponse:
        require_login(request)
        await check_csrf(request)
        try:
            clip = await run_in_threadpool(make, *args)
        except AppError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"url": f"/speech/clips/{clip.name}"})

    @app.post("/speech/note/{note_id}")
    async def speak_note(request: Request, note_id: int):
        return await speech_reply(request, core.speak_note, note_id)

    @app.post("/speech/chat/{message_id}")
    async def speak_chat(request: Request, message_id: int):
        return await speech_reply(request, core.speak_chat, message_id)

    @app.post("/speech/hint/{attempt_id}/{level}")
    async def speak_hint(request: Request, attempt_id: int, level: int):
        return await speech_reply(request, core.speak_hint, attempt_id, level)

    @app.get("/speech/clips/{name}")
    def speech_clip(request: Request, name: str):
        require_login(request)
        path = core.speech_clip_path(name)
        if path is None:
            return JSONResponse({"error": "звук не найден"}, status_code=404)
        return FileResponse(
            path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"}
        )

    @app.post("/mistakes/{mistake_id}/ai")
    async def ai_mistake(
        request: Request, mistake_id: int, back: Annotated[str, Form()] = "/mistakes"
    ):
        require_login(request)
        await check_csrf(request)
        try:
            await run_in_threadpool(core.ai_classify_mistake, mistake_id)
        except AppError as e:
            flash(request, str(e), "warning")
        return redirect(_safe_next(back))

    @app.post("/tasks/{task_id}/part2")
    async def ai_part2(request: Request, task_id: int, solution: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        try:
            grade = await run_in_threadpool(core.ai_grade_part2, task_id, solution)
        except AppError as e:
            flash(request, str(e), "warning")
            return redirect(f"/tasks/{task_id}#part2")
        return redirect(f"/grades/{grade.id}")

    @app.get("/grades/{grade_id}", response_class=HTMLResponse)
    def grade_page(request: Request, grade_id: int):
        require_login(request)
        try:
            grade = core.part2_grade(grade_id)
            task = core.task(grade.task_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/ai")
        return render(request, "grade.html", grade=grade, task=task)

    @app.post("/tasks/{task_id}/generate")
    async def ai_generate(request: Request, task_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            made = await run_in_threadpool(core.ai_generate_similar, task_id)
        except AppError as e:
            flash(request, str(e), "warning")
            return redirect(f"/tasks/{task_id}")
        if made.task.can_practice:
            flash(
                request, f"ИИ составил задачу, CORE проверил ответ: {made.check_note}.", "success"
            )
        else:
            flash(
                request,
                f"ИИ составил задачу, но ответ не проверен ({made.check_note}). "
                "Сверь его сам на странице «Проверка».",
                "warning",
            )
        return redirect(f"/tasks/{made.task.id}")

    @app.get("/ai", response_class=HTMLResponse)
    def ai_page(request: Request):
        require_login(request)
        return render(
            request,
            "ai.html",
            ai=core.ai_status(),
            calls=core.ai_calls(limit=50),
            grades=core.part2_grades(),
        )

    @app.post("/attempts/{attempt_id}/give-up")
    async def give_up(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            core.give_up(attempt_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/attempts/{attempt_id}")
        session_id = core.diagnostic_session_of_attempt(attempt_id)
        if session_id is not None:
            return after_diagnostic_answer(session_id)
        return redirect(f"/attempts/{attempt_id}")

    @app.post("/attempts/{attempt_id}/similar")
    async def similar(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        if core.diagnostic_session_of_attempt(attempt_id) is not None:
            flash(request, "в диагностике похожих задач и подсказок нет", "warning")
            return redirect(f"/attempts/{attempt_id}")
        try:
            attempt = core.attempt(attempt_id)
            if attempt.status == AttemptStatus.IN_PROGRESS:
                core.give_up(attempt_id)  # похожая задача = сдался на этой (подсказка 5)
            found = core.similar_task(attempt.task_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/attempts/{attempt_id}")
        if found is None:
            flash(request, "Похожих проверенных задач пока нет.", "warning")
            return redirect(f"/attempts/{attempt_id}")
        return start_and_open(request, found.id)

    @app.post("/attempts/{attempt_id}/abandon")
    async def abandon(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            core.abandon_attempt(attempt_id)
        except AppError as e:
            flash(request, str(e), "error")
        return redirect("/")

    @app.get("/attempts", response_class=HTMLResponse)
    def attempts_page(request: Request, task: str | None = None):
        require_login(request)
        return render(request, "attempts.html", attempts=core.attempts(_parse_int(task), limit=200))

    # ── проверка эталонных ответов ──

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request):
        require_login(request)
        skipped = request.session.get("review_skip", [])
        task = core.next_unverified_task(exclude=skipped)
        return render(request, "review.html", task=task, skipped=len(skipped))

    @app.post("/review/{task_id}")
    async def review_task(request: Request, task_id: int, decision: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        if decision == "skip":
            skipped = request.session.get("review_skip", [])
            request.session["review_skip"] = [*skipped, task_id][-500:]
            return redirect("/review")
        if decision == "reset":
            request.session.pop("review_skip", None)
            return redirect("/review")
        if decision not in ("yes", "no"):
            flash(request, "Выбери «верный» или «неверный».", "error")
            return redirect("/review")
        try:
            core.review_task(task_id, answer_is_correct=decision == "yes")
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/review")
        if decision == "yes":
            flash(request, f"Задача {task_id} проверена, её можно решать.", "success")
        else:
            flash(request, f"Задача {task_id} помечена как спорная и не будет выдаваться.")
        return redirect("/review")

    # ── профиль ──

    @app.get("/profile", response_class=HTMLResponse)
    def profile_page(request: Request):
        require_login(request)
        return render(request, "profile.html", profile=core.profile())

    @app.post("/profile")
    async def profile_save(
        request: Request,
        display_name: Annotated[str, Form()] = "",
        target_math: Annotated[str, Form()] = "",
        target_informatics: Annotated[str, Form()] = "",
    ):
        require_login(request)
        await check_csrf(request)
        targets = {}
        for subject, text in (
            (Subject.MATH_PROFILE, target_math),
            (Subject.INFORMATICS, target_informatics),
        ):
            value = _parse_int(text)
            if text and value is None:
                flash(request, "Целевой балл — целое число от 0 до 100.", "error")
                return redirect("/profile")
            if value is not None:
                targets[subject] = value
        try:
            core.update_profile(display_name=display_name, targets=targets)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/profile")
        flash(request, "Профиль сохранён.", "success")
        return redirect("/profile")

    # ── импорт ──

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request):
        require_login(request)
        return render(request, "import.html", batches=core.import_batches())

    @app.post("/import/preview", response_class=HTMLResponse)
    async def import_preview(request: Request, file: UploadFile):
        require_login(request)
        await check_csrf(request)
        uploads.remove_stale(upload_root)
        try:
            token, path = uploads.save_upload(upload_root, file.filename or "", file.file)
        except uploads.UploadError as e:
            flash(request, str(e), "error")
            return redirect("/import")
        report = core.preview_import(path)
        can_apply = bool(report.accepted) and not report.file_error
        if not can_apply:
            uploads.discard(upload_root, token)
        return render(
            request,
            "import_report.html",
            report=report,
            token=token if can_apply else None,
        )

    @app.post("/import/apply")
    async def import_apply(request: Request, token: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        try:
            path = uploads.find_task_file(upload_root, token)
        except uploads.UploadError as e:
            flash(request, str(e), "error")
            return redirect("/import")
        try:
            result = core.import_tasks(path)
        finally:
            uploads.discard(upload_root, token)
        if result.batch is None:
            flash(request, "Ничего не добавлено: в файле нет годных задач.", "error")
        else:
            flash(
                request,
                f"Добавлено задач: {result.batch.added_count} (импорт №{result.batch.id}). "
                "Новые задачи нужно проверить на странице «Проверка».",
                "success",
            )
        return redirect("/import")

    @app.post("/imports/{batch_id}/undo")
    async def import_undo(request: Request, batch_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            batch = core.rollback_import(batch_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/import")
        flash(
            request,
            f"Импорт №{batch.id} отменён, задач выведено из оборота: {batch.added_count}.",
            "success",
        )
        return redirect("/import")

    # ── резервная копия ──

    @app.post("/backup")
    async def backup(request: Request):
        require_login(request)
        await check_csrf(request)
        try:
            path = core.backup()
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    return app
