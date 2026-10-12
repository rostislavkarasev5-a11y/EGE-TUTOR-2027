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
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from ege_tutor import __version__
from ege_tutor.core.app import AppError, TutorApp, parse_time
from ege_tutor.core.domain import (
    AI_LABEL,
    AI_PURPOSE_NAMES,
    CODE_VERDICT_LABELS,
    EVENT_KIND_NAMES,
    ITEM_BASIS_NAMES,
    LESSON_STATUS_NAMES,
    LESSON_STEP_NAMES,
    LESSON_STEPS,
    MISTAKE_CATEGORY_NAMES,
    SOURCE_LABELS,
    STOP_REASON_NAMES,
    WEEKDAY_NAMES,
    AnswerType,
    AttemptStatus,
    CodeVerdict,
    ControlStatus,
    DiagnosticStatus,
    DisciplineColor,
    EventKind,
    ImportBatchStatus,
    ItemBasis,
    LessonStatus,
    LessonStep,
    MistakeCategory,
    PlanItemKind,
    PlanItemStatus,
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


def theory_html(text: str) -> Markup:
    """Текст теории в HTML: «## » — заголовок, «- » — пункт списка, пустая строка — абзац.

    Всё остальное экранируется: разметка в тексте теории не исполняется.
    """
    out: list[str] = []
    items: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            out.append(f"<h3>{escape(line.lstrip('#').strip())}</h3>")
        elif line.startswith(("- ", "* ")):
            if paragraph:
                flush()
            items.append(str(escape(line[2:].strip())))
        else:
            if items:
                flush()
            paragraph.append(str(escape(line)))
    flush()
    return Markup("\n".join(out))


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


def _parse_date(text: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _parse_local(text: str | None) -> dt.datetime | None:
    """Поле datetime-local («2026-10-07T16:30») → местное время без часового пояса."""
    try:
        return dt.datetime.fromisoformat(text).replace(tzinfo=None) if text else None
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
        PlanItemKind=PlanItemKind,
        LessonStep=LessonStep,
        LessonStatus=LessonStatus,
        LESSON_STEPS=LESSON_STEPS,
        LESSON_STEP_NAMES=LESSON_STEP_NAMES,
        LESSON_STATUS_NAMES=LESSON_STATUS_NAMES,
        PlanItemStatus=PlanItemStatus,
        ControlStatus=ControlStatus,
        DisciplineColor=DisciplineColor,
        EventKind=EventKind,
        EVENT_KIND_NAMES=EVENT_KIND_NAMES,
        WEEKDAY_NAMES=WEEKDAY_NAMES,
        AI_LABEL=AI_LABEL,
        AI_PURPOSE_NAMES=AI_PURPOSE_NAMES,
        skill_title=tutor.skill_title,
        time_limit=f"{tutor.settings.app.sandbox.time_limit_seconds:g}",
        memory_limit=tutor.settings.app.sandbox.memory_limit_mb,
        speech_max_seconds=tutor.settings.app.speech.max_recording_seconds,
        version=__version__,
    )
    templates.env.filters.update(
        minutes=minutes, display_answer=display_answer, utc_time=utc_time, theory_html=theory_html
    )

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
            plan=core.daily_plan(),
            checkin=core.checkin(),
            discipline=core.discipline(),
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

    # ── план, расписание, дисциплина, контрольная (Phase 7) ──

    @app.get("/plan", response_class=HTMLResponse)
    def plan_page(request: Request):
        require_login(request)
        plan = core.daily_plan()
        used, limit = core.plan_change_limit(plan)
        today = core.today()
        return render(
            request,
            "plan.html",
            plan=plan,
            items=sorted(plan.items, key=lambda i: (not i.active, i.position, i.id)),
            budget=core.day_budget(),
            checkin=core.checkin(),
            discipline=core.discipline(),
            change_used=used,
            change_limit=limit,
            tomorrow=(today + dt.timedelta(days=1)).isoformat(),
            today=today,
        )

    async def plan_action(request: Request, action, success: str | None = None):
        """Общая обёртка для кнопок плана: CSRF, ошибка — сообщением, возврат на /plan."""
        require_login(request)
        await check_csrf(request)
        try:
            action()
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/plan")
        if success:
            flash(request, success, "success")
        return redirect("/plan")

    @app.post("/checkin")
    async def save_checkin(
        request: Request,
        fatigue: Annotated[str, Form()] = "",
        available: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        back: Annotated[str, Form()] = "/plan",
    ):
        require_login(request)
        await check_csrf(request)
        level = _parse_int(fatigue)
        minutes_free = _parse_int(available)
        if level is None or (available and minutes_free is None):
            flash(request, "Усталость — от 1 до 5, время — целое число минут.", "error")
            return redirect(_safe_next(back))
        try:
            core.save_checkin(level, minutes_free, note)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(_safe_next(back))
        flash(request, "Чек-ин сохранён. Чтобы план учёл его, нажми «Перестроить».", "success")
        return redirect(_safe_next(back))

    @app.post("/plan/rebuild")
    async def rebuild_plan(request: Request):
        return await plan_action(request, core.rebuild_plan, "План перестроен.")

    @app.post("/plan/add")
    async def add_plan_item(
        request: Request,
        subject: Annotated[str, Form()] = "",
        item: Annotated[str, Form()] = "",
        tasks: Annotated[str, Form()] = "1",
    ):
        chosen = _parse_subject(subject)
        number = _parse_int(item)
        count = _parse_int(tasks) or 1

        def add():
            if chosen is None or number is None:
                raise AppError("выбери предмет и номер задания")
            core.add_plan_item(chosen, number, count)

        return await plan_action(request, add, "Пункт добавлен.")

    @app.post("/plan/items/{item_id}/start")
    async def start_plan_item(request: Request, item_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            attempt = core.start_plan_item(item_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/plan")
        return redirect(f"/attempts/{attempt.id}")

    @app.post("/plan/items/{item_id}/up")
    async def plan_item_up(request: Request, item_id: int):
        return await plan_action(request, lambda: core.reorder_plan_item(item_id, True))

    @app.post("/plan/items/{item_id}/down")
    async def plan_item_down(request: Request, item_id: int):
        return await plan_action(request, lambda: core.reorder_plan_item(item_id, False))

    @app.post("/plan/items/{item_id}/move")
    async def move_plan_item(
        request: Request,
        item_id: int,
        day: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
    ):
        target = _parse_date(day)

        def move():
            if target is None:
                raise AppError("выбери день, на который перенести")
            core.move_plan_item(item_id, target, note)

        return await plan_action(request, move, "Пункт перенесён.")

    @app.post("/plan/items/{item_id}/remove")
    async def remove_plan_item(request: Request, item_id: int):
        return await plan_action(request, lambda: core.remove_plan_item(item_id), "Пункт убран.")

    @app.post("/plan/items/{item_id}/excuse")
    async def excuse_plan_item(request: Request, item_id: int, note: Annotated[str, Form()] = ""):
        return await plan_action(
            request,
            lambda: core.excuse_plan_item(item_id, note),
            "Отмечена объективная причина. Обязательный пункт перенесён на ближайший учебный день.",
        )

    @app.post("/plan/excuse-day")
    async def excuse_day(request: Request, note: Annotated[str, Form()] = ""):
        return await plan_action(
            request,
            lambda: core.excuse_day(note),
            "День отмечен объективной причиной: обязательные пункты перенесены.",
        )

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_page(request: Request):
        require_login(request)
        return render(
            request,
            "calendar.html",
            windows=core.calendar_windows(),
            events=core.calendar_events(),
            today=core.today(),
        )

    async def calendar_action(request: Request, action, success: str):
        require_login(request)
        await check_csrf(request)
        try:
            action()
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/calendar")
        flash(request, success, "success")
        return redirect("/calendar")

    @app.post("/calendar/windows")
    async def add_window(
        request: Request,
        weekday: Annotated[str, Form()] = "",
        start: Annotated[str, Form()] = "",
        end: Annotated[str, Form()] = "",
    ):
        day = _parse_int(weekday)

        def add():
            if day is None:
                raise AppError("выбери день недели")
            core.add_calendar_window(day, parse_time(start), parse_time(end))

        return await calendar_action(request, add, "Окно для учёбы добавлено.")

    @app.post("/calendar/windows/{window_id}/delete")
    async def delete_window(request: Request, window_id: int):
        return await calendar_action(
            request, lambda: core.delete_calendar_window(window_id), "Окно удалено."
        )

    @app.post("/calendar/events")
    async def add_event(
        request: Request,
        kind: Annotated[str, Form()] = "",
        title: Annotated[str, Form()] = "",
        starts_at: Annotated[str, Form()] = "",
        ends_at: Annotated[str, Form()] = "",
        blocks_study: Annotated[str, Form()] = "",
    ):
        begin, finish = _parse_local(starts_at), _parse_local(ends_at)

        def add():
            try:
                event_kind = EventKind(kind)
            except ValueError:
                raise AppError("выбери тип события") from None
            if begin is None or finish is None:
                raise AppError("укажи начало и конец события")
            core.add_calendar_event(event_kind, title, begin, finish, blocks_study == "on")

        return await calendar_action(request, add, "Событие добавлено.")

    @app.post("/calendar/events/{event_id}/delete")
    async def delete_event(request: Request, event_id: int):
        return await calendar_action(
            request, lambda: core.delete_calendar_event(event_id), "Событие удалено."
        )

    @app.get("/control", response_class=HTMLResponse)
    def control_page(request: Request):
        require_login(request)
        return render(
            request,
            "control.html",
            sessions=core.control_sessions(limit=30),
            config=tutor.settings.planner.control,
        )

    @app.post("/control/start")
    async def start_control(
        request: Request,
        subject: Annotated[str, Form()] = "",
        item: Annotated[str, Form()] = "",
    ):
        require_login(request)
        await check_csrf(request)
        chosen = _parse_subject(subject)
        number = _parse_int(item)
        if chosen is None or number is None:
            flash(request, "выбери предмет и номер задания", "error")
            return redirect("/control")
        try:
            session = core.start_control(chosen, number)
            return after_control_answer(session.id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/control")

    @app.get("/control/{session_id}", response_class=HTMLResponse)
    def control_result_page(request: Request, session_id: int):
        require_login(request)
        try:
            session = core.control_session(session_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/control")
        results = core.control_results(session_id)
        return render(
            request,
            "control_result.html",
            session=session,
            results=results,
            tasks={r.task_id: core.task(r.task_id) for r in results},
            slow_factor=tutor.settings.planner.control.slow_factor,
        )

    @app.post("/control/{session_id}/continue")
    async def continue_control(request: Request, session_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            return after_control_answer(session_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/control/{session_id}")

    @app.post("/control/{session_id}/finish")
    async def finish_control(request: Request, session_id: int):
        require_login(request)
        await check_csrf(request)
        try:
            core.finish_control(session_id)
        except AppError as e:
            flash(request, str(e), "error")
        return redirect(f"/control/{session_id}")

    # ── учёба (Phase 8, ADR-0022) ──

    @app.get("/learn", response_class=HTMLResponse)
    def learn_page(request: Request):
        require_login(request)
        lessons = core.lessons(limit=100)
        return render(
            request,
            "learn.html",
            suggestions=[s for s in (core.lesson_suggestion(subj) for subj in Subject) if s],
            active=[x for x in lessons if x.status == LessonStatus.ACTIVE],
            finished=[x for x in lessons if x.status != LessonStatus.ACTIVE][:20],
            topics={subj: core.catalog.topics_of(subj) for subj in Subject},
            has_theory=core.has_theory,
        )

    @app.get("/learn/skill/{skill_code}")
    def learn_skill(request: Request, skill_code: str):
        """Блок по навыку: открыть начатый или предложить начать."""
        require_login(request)
        try:
            subject, skill = core.skill(skill_code)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/learn")
        active = core.active_lesson(skill_code)
        if active is not None:
            return redirect(f"/lessons/{active.id}")
        return render(
            request,
            "lesson_start.html",
            subject=subject,
            skill=skill,
            theory=core.theory(skill_code),
            config=tutor.settings.learning,
        )

    @app.post("/learn/start")
    async def learn_start(request: Request, skill_code: Annotated[str, Form()] = ""):
        require_login(request)
        await check_csrf(request)
        try:
            lesson = core.start_lesson(skill_code)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/learn")
        return redirect(f"/lessons/{lesson.id}")

    @app.get("/lessons/{lesson_id}", response_class=HTMLResponse)
    def lesson_page(request: Request, lesson_id: int):
        require_login(request)
        try:
            progress = core.lesson_progress(lesson_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/learn")
        lesson = progress.lesson
        subject, skill = core.skill(lesson.skill_code)
        check = core.lesson_check(lesson_id)
        tasks = core.lesson_tasks(lesson_id)
        review = []
        if lesson.step == LessonStep.MISTAKE_REVIEW:
            by_attempt = {t.attempt_id: t for t in tasks}
            for attempt_id in check.problems:
                item = by_attempt[attempt_id]
                review.append((item, core.attempt(attempt_id), core.task(item.task_id)))
        return render(
            request,
            "lesson.html",
            lesson=lesson,
            progress=progress,
            subject=subject,
            skill=skill,
            theory=core.theory(lesson.skill_code),
            check=check,
            tasks=tasks,
            review=review,
            config=tutor.settings.learning,
        )

    async def lesson_action(request: Request, lesson_id: int, action) -> RedirectResponse:
        require_login(request)
        await check_csrf(request)
        try:
            action()
        except AppError as e:
            flash(request, str(e), "error")
        return redirect(f"/lessons/{lesson_id}")

    @app.post("/lessons/{lesson_id}/confirm")
    async def lesson_confirm(request: Request, lesson_id: int):
        return await lesson_action(request, lesson_id, lambda: core.confirm_lesson_step(lesson_id))

    @app.post("/lessons/{lesson_id}/reviewed/{attempt_id}")
    async def lesson_reviewed(request: Request, lesson_id: int, attempt_id: int):
        return await lesson_action(
            request, lesson_id, lambda: core.mark_lesson_mistake_reviewed(lesson_id, attempt_id)
        )

    @app.post("/lessons/{lesson_id}/abandon")
    async def lesson_abandon(request: Request, lesson_id: int):
        return await lesson_action(request, lesson_id, lambda: core.abandon_lesson(lesson_id))

    @app.post("/lessons/{lesson_id}/next")
    async def lesson_next(request: Request, lesson_id: int):
        """Следующая задача шага. Если задач на шаге больше нет — на страницу блока."""
        require_login(request)
        await check_csrf(request)
        try:
            attempt = core.lesson_attempt(lesson_id)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/lessons/{lesson_id}")
        if attempt is None:
            return redirect(f"/lessons/{lesson_id}")
        return redirect(f"/attempts/{attempt.id}")

    def show_theory(
        request: Request, skill_code: str, retold: str | None = None, retold_for: int = -1
    ):
        try:
            subject, skill = core.skill(skill_code)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect("/learn")
        return render(
            request,
            "theory.html",
            subject=subject,
            skill=skill,
            theory=core.theory(skill_code),
            active=core.active_lesson(skill_code),
            ai=core.ai_status(),
            retold=retold,
            retold_for=retold_for,
        )

    @app.get("/theory/{skill_code}", response_class=HTMLResponse)
    def theory_page(request: Request, skill_code: str):
        require_login(request)
        return show_theory(request, skill_code)

    @app.post("/theory/{skill_code}/retell", response_class=HTMLResponse)
    async def theory_retell(
        request: Request, skill_code: str, example: Annotated[str, Form()] = ""
    ):
        """«Объясни иначе»: пересказ ИИ, показывается сразу и не сохраняется (ADR-0022)."""
        require_login(request)
        await check_csrf(request)
        number = _parse_int(example)
        try:
            text = core.retell_theory(skill_code, number)
        except AppError as e:
            flash(request, str(e), "error")
            return redirect(f"/theory/{skill_code}")
        return show_theory(request, skill_code, text, number or 0)

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
        control_id = core.control_session_of_attempt(attempt_id)
        if control_id is not None and attempt.status != AttemptStatus.IN_PROGRESS:
            return redirect(f"/control/{control_id}")
        control = core.control_session(control_id) if control_id is not None else None
        lesson_id = core.lesson_of_attempt(attempt_id)
        lesson = core.lesson(lesson_id) if lesson_id is not None else None
        notes = request.session.get("result_notes", {})
        subject, item = request.session.get("solve_filter", ["", ""])
        runs = []
        code_enabled = task.subject == Subject.INFORMATICS
        if code_enabled:
            runs = core.code_runs(task.id, attempt_id, limit=5)
        mistakes = core.attempt_mistakes(attempt_id)
        ai = core.ai_status()
        ai_allowed = session_id is None and control is None and core.ai_allowed_for(attempt_id)
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
            control=control,
            lesson=lesson,
            control_done=(
                sum(1 for r in core.control_results(control.id) if r.attempt_id is not None)
                if control is not None
                else 0
            ),
        )

    def after_control_answer(session_id: int):
        """После ответа в контрольной — следующая задача или итог."""
        step = core.control_step(session_id)
        if step.attempt is not None:
            return redirect(f"/attempts/{step.attempt.id}")
        return redirect(f"/control/{session_id}")

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
        control_id = core.control_session_of_attempt(attempt_id)
        if control_id is not None:
            return after_control_answer(control_id)
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
        control_id = core.control_session_of_attempt(attempt_id)
        if control_id is not None:
            return after_control_answer(control_id)
        return redirect(f"/attempts/{attempt_id}")

    @app.post("/attempts/{attempt_id}/similar")
    async def similar(request: Request, attempt_id: int):
        require_login(request)
        await check_csrf(request)
        if core.diagnostic_session_of_attempt(attempt_id) is not None:
            flash(request, "в диагностике похожих задач и подсказок нет", "warning")
            return redirect(f"/attempts/{attempt_id}")
        if core.control_session_of_attempt(attempt_id) is not None:
            flash(request, "в контрольной похожих задач и подсказок нет", "warning")
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
        return render(
            request, "profile.html", profile=core.profile(), utc_offset=core.utc_offset_hours()
        )

    @app.post("/profile")
    async def profile_save(
        request: Request,
        display_name: Annotated[str, Form()] = "",
        target_math: Annotated[str, Form()] = "",
        target_informatics: Annotated[str, Form()] = "",
        utc_offset: Annotated[str, Form()] = "",
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
        offset = _parse_int(utc_offset)
        if utc_offset and offset is None:
            flash(request, "Часовой пояс — целое число часов, например 3 для Москвы.", "error")
            return redirect("/profile")
        try:
            core.update_profile(display_name=display_name, targets=targets, utc_offset_hours=offset)
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
