"""Сайт (ADR-0013): вход, защита форм, решение задач, импорт, копия базы."""

import io
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from ege_tutor.interfaces.web.app import create_app
from ege_tutor.interfaces.web.auth import LoginThrottle, PasswordStore, web_dir
from tests.conftest import REPO_ROOT

PASSWORD = "-".join(["очень", "длинный", "пароль"])  # тестовый пароль собирается при запуске
SAMPLE_DIR = REPO_ROOT / "content" / "sample"


def _csrf(html: str) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', html)
    assert found, html
    return found.group(1)


@pytest.fixture
def store(tutor):
    passwords = PasswordStore(web_dir(tutor.settings.data_dir) / "password.argon2")
    passwords.set(PASSWORD)
    return passwords


@pytest.fixture
def anon(tutor, store):
    """Посетитель без входа."""
    return TestClient(create_app(tutor, password_store=store), base_url="https://testserver")


@pytest.fixture
def client(anon):
    """Владелец, вошедший на сайт."""
    page = anon.get("/login")
    response = anon.post(
        "/login", data={"csrf": _csrf(page.text), "password": PASSWORD, "next": "/"}
    )
    assert response.status_code == 200
    assert "Решать задачи" in response.text
    return anon


def post(client: TestClient, path: str, data: dict | None = None, **kwargs):
    """POST с CSRF-токеном текущей сессии."""
    token = _csrf(client.get("/profile").text)
    return client.post(path, data={"csrf": token, **(data or {})}, **kwargs)


def _sample_zip(extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.write(SAMPLE_DIR / "tasks.yaml", "tasks.yaml")
        zf.write(SAMPLE_DIR / "files" / "numbers.txt", "files/numbers.txt")
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _import_sample(client: TestClient) -> None:
    token = _csrf(client.get("/import").text)
    preview = client.post(
        "/import/preview",
        data={"csrf": token},
        files={"file": ("sample.zip", _sample_zip(), "application/zip")},
    )
    assert preview.status_code == 200, preview.text
    assert "годных: <strong>5</strong>" in preview.text
    upload = re.search(r'name="token" value="([^"]+)"', preview.text).group(1)
    applied = post(client, "/import/apply", {"token": upload})
    assert "Добавлено задач: 5" in applied.text


def _review_all(client: TestClient) -> None:
    for _ in range(5):
        page = client.get("/review")
        task_id = re.search(r'action="/review/(\d+)"', page.text).group(1)
        post(client, f"/review/{task_id}", {"decision": "yes"})
    assert "Непроверенных задач нет" in client.get("/review").text


def _start(client: TestClient, task_id: int) -> str:
    response = post(client, f"/tasks/{task_id}/start")
    assert response.status_code == 200
    return str(response.url).rsplit("/", 1)[-1]


# ── вход и защита ───────────────────────────────────────────────────────────


def test_pages_require_login(anon):
    for path in ("/", "/tasks", "/review", "/attempts", "/import", "/profile", "/tasks/1"):
        response = anon.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?next=")


def test_health_check_is_public(anon):
    assert anon.get("/healthz").json()["status"] == "ok"


def test_wrong_password_is_rejected(anon):
    page = anon.get("/login")
    response = anon.post("/login", data={"csrf": _csrf(page.text), "password": "не тот"})
    assert response.status_code == 401
    assert "Неверный пароль" in response.text
    assert anon.get("/", follow_redirects=False).status_code == 303


def test_login_is_locked_after_repeated_failures(tutor, store):
    client = TestClient(
        create_app(tutor, password_store=store, throttle=LoginThrottle(max_failures=3)),
        base_url="https://testserver",
    )
    token = _csrf(client.get("/login").text)
    for _ in range(3):
        client.post("/login", data={"csrf": token, "password": "не тот"})
    # даже верный пароль не пускает, пока действует блокировка
    response = client.post("/login", data={"csrf": token, "password": PASSWORD})
    assert response.status_code == 429
    assert "Слишком много неверных попыток" in response.text


def test_throttle_unlocks_after_timeout():
    now = [0.0]
    throttle = LoginThrottle(max_failures=2, lock_seconds=60, clock=lambda: now[0])
    throttle.failure("ip")
    assert throttle.seconds_locked("ip") == 0
    throttle.failure("ip")
    assert throttle.seconds_locked("ip") > 0
    now[0] = 61
    assert throttle.seconds_locked("ip") == 0


def test_login_needs_csrf_token(anon):
    anon.get("/login")
    response = anon.post("/login", data={"password": PASSWORD})
    assert response.status_code == 400
    assert "Форма устарела" in response.text


def test_forms_need_csrf_token(client):
    response = client.post("/profile", data={"display_name": "Взлом"})
    assert response.status_code == 400
    assert "Взлом" not in client.get("/profile").text


def test_login_does_not_redirect_to_other_sites(anon):
    page = anon.get("/login?next=//evil.example")
    response = anon.post(
        "/login",
        data={"csrf": _csrf(page.text), "password": PASSWORD, "next": "//evil.example"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_login_returns_to_requested_page(anon):
    page = anon.get("/attempts")  # перенаправит на вход
    response = anon.post(
        "/login",
        data={"csrf": _csrf(page.text), "password": PASSWORD, "next": "/attempts"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/attempts"


def test_session_cookie_is_protected(anon):
    page = anon.get("/login")
    response = anon.post(
        "/login",
        data={"csrf": _csrf(page.text), "password": PASSWORD},
        follow_redirects=False,
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store"
    assert "max-age" in headers["strict-transport-security"]


def test_logout(client):
    post(client, "/logout")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_page_warns_when_password_not_set(tutor):
    empty = PasswordStore(web_dir(tutor.settings.data_dir) / "nothing.argon2")
    client = TestClient(create_app(tutor, password_store=empty), base_url="https://testserver")
    page = client.get("/login")
    assert "Пароль ещё не задан" in page.text
    response = client.post("/login", data={"csrf": _csrf(page.text), "password": ""})
    assert response.status_code == 401


# ── пароль ──────────────────────────────────────────────────────────────────


def test_password_store(tmp_path):
    passwords = PasswordStore(tmp_path / "web" / "password.argon2")
    assert not passwords.is_set()
    with pytest.raises(ValueError, match="не короче"):
        passwords.set("short")
    passwords.set(PASSWORD)
    assert passwords.verify(PASSWORD)
    assert not passwords.verify(PASSWORD + "x")
    assert PASSWORD not in passwords.path.read_text(encoding="utf-8")  # хранится только хеш


# ── задачи, проверка и решение ──────────────────────────────────────────────


def test_full_flow_import_review_solve(client):
    _import_sample(client)
    tasks = client.get("/tasks").text
    assert "Сгенерировано ИИ — не задание ФИПИ" in tasks  # метка ИИ видна (ADR-0007)
    assert "не проверена" in tasks

    # пока ответ не проверен, решать нельзя
    response = post(client, "/tasks/2/start")
    assert "Решать пока нельзя" in response.text

    _review_all(client)

    attempt_id = _start(client, 2)
    page = client.get(f"/attempts/{attempt_id}").text
    assert "Попытка №1" in page
    assert 'id="timer"' in page

    hinted = post(client, f"/attempts/{attempt_id}/hint")
    assert "Уровень 1" in hinted.text

    wrong = post(client, f"/attempts/{attempt_id}/answer", {"answer": "2/5"})
    assert "неверный формат" in wrong.text
    assert "0,4" in wrong.text  # пояснение, как записать ответ
    assert "Попробовать ещё раз" in wrong.text

    retry_id = _start(client, 2)
    page = client.get(f"/attempts/{retry_id}").text
    assert "Подсказки из прошлой попытки учтены" in page
    right = post(client, f"/attempts/{retry_id}/answer", {"answer": "0,4"})
    assert "Итог: верно" in right.text
    assert "не считается самостоятельным" in right.text

    history = client.get("/attempts").text
    assert "2/5" in history
    assert "0,4" in history


def test_solve_next_and_independent_answer(client):
    _import_sample(client)
    _review_all(client)
    response = post(client, "/solve", {"subject": "math", "item": "6"})
    attempt_id = str(response.url).rsplit("/", 1)[-1]
    done = post(client, f"/attempts/{attempt_id}/answer", {"answer": "6"})
    assert "Решено самостоятельно" in done.text
    # повторная отправка той же формы не создаёт вторую запись
    again = post(client, f"/attempts/{attempt_id}/answer", {"answer": "6"})
    assert "уже завершена" in again.text


def test_solve_without_tasks_explains_what_to_do(client):
    response = post(client, "/solve", {"subject": "", "item": ""})
    assert "нет задач для решения" in response.text


def test_empty_answer_is_not_recorded(client):
    _import_sample(client)
    _review_all(client)
    attempt_id = _start(client, 1)
    response = post(client, f"/attempts/{attempt_id}/answer", {"answer": "  "})
    assert "пустой ответ" in response.text
    assert 'name="answer"' in response.text  # попытка продолжается


def test_give_up_shows_answer(client):
    _import_sample(client)
    _review_all(client)
    attempt_id = _start(client, 2)
    response = post(client, f"/attempts/{attempt_id}/give-up")
    assert "Ты сдался" in response.text
    assert "Правильный ответ: <strong>0,4</strong>" in response.text
    assert "сдался" in client.get("/attempts").text


def test_similar_task_and_abandon(client):
    _import_sample(client)
    _review_all(client)
    attempt_id = _start(client, 1)
    response = post(client, f"/attempts/{attempt_id}/similar")
    # других задач №6 по математике нет — остаёмся на той же попытке
    assert "Похожих проверенных задач пока нет" in response.text
    other = _start(client, 3)
    post(client, f"/attempts/{other}/abandon")
    assert "брошена" in client.get("/attempts").text


def test_task_page_hides_answer_until_asked(client):
    _import_sample(client)
    page = client.get("/tasks/2").text
    assert "Правильный ответ" not in page
    assert "Правильный ответ" in client.get("/tasks/2?answer=1").text


def test_task_file_download(client):
    _import_sample(client)
    page = client.get("/tasks/5").text
    assert "numbers.txt" in page
    response = client.get("/tasks/5/files/0")
    assert response.status_code == 200
    assert response.content == (SAMPLE_DIR / "files" / "numbers.txt").read_bytes()
    assert client.get("/tasks/5/files/7").url.path == "/tasks"


def test_missing_task_and_attempt(client):
    assert "не найдена" in client.get("/tasks/999").text
    assert "не найдена" in client.get("/attempts/999").text


def test_review_no_and_skip(client):
    _import_sample(client)
    first = re.search(r'action="/review/(\d+)"', client.get("/review").text).group(1)
    response = post(client, f"/review/{first}", {"decision": "skip"})
    second = re.search(r'action="/review/(\d+)"', response.text).group(1)
    assert second != first
    post(client, f"/review/{second}", {"decision": "no"})
    assert "спорная" in client.get("/tasks").text


# ── профиль ─────────────────────────────────────────────────────────────────


def test_profile_save_and_validation(client):
    saved = post(
        client,
        "/profile",
        {"display_name": "Ученик", "target_math": "92", "target_informatics": "95"},
    )
    assert "Профиль сохранён" in saved.text
    assert 'value="92"' in saved.text
    assert "Привет, Ученик!" in client.get("/").text
    bad = post(client, "/profile", {"target_math": "150"})
    assert "от 0 до 100" in bad.text
    bad = post(client, "/profile", {"target_math": "много"})
    assert "целое число" in bad.text


# ── импорт ──────────────────────────────────────────────────────────────────


def _preview(client: TestClient, name: str, content: bytes):
    token = _csrf(client.get("/import").text)
    return client.post(
        "/import/preview", data={"csrf": token}, files={"file": (name, content, "text/plain")}
    )


def test_import_rejects_wrong_file_type(client):
    response = _preview(client, "tasks.exe", b"MZ")
    assert "нужен файл .yaml, .csv" in response.text


def test_import_rejects_unsafe_archive(client):
    response = _preview(client, "bad.zip", _sample_zip({"../evil.txt": b"x"}))
    assert "недопустимый путь" in response.text


def test_import_needs_exactly_one_task_file(client):
    response = _preview(client, "two.zip", _sample_zip({"more.yaml": b"tasks: []"}))
    assert "ровно один файл задач" in response.text


def test_import_reports_errors_without_writing(client):
    response = _preview(client, "broken.yaml", b"tasks: [{subject: math}]")
    assert "Добавить нечего" in response.text
    assert "Импортов пока не было" in client.get("/import").text


def test_import_yaml_without_assets_reports_missing_file(client):
    content = (SAMPLE_DIR / "tasks.yaml").read_bytes()
    response = _preview(client, "tasks.yaml", content)
    assert "файл не найден: files/numbers.txt" in response.text
    assert "годных: <strong>4</strong>" in response.text


def test_import_apply_with_stale_token(client):
    response = post(client, "/import/apply", {"token": "x" * 32})
    assert "загрузи файл заново" in response.text
    response = post(client, "/import/apply", {"token": "../../etc"})
    assert "загрузи файл заново" in response.text


def test_import_undo(client):
    _import_sample(client)
    response = post(client, "/imports/1/undo")
    assert "Импорт №1 отменён" in response.text
    again = post(client, "/imports/1/undo")
    assert "Ошибка" not in again.text
    assert "отменён" in again.text


# ── резервная копия ─────────────────────────────────────────────────────────


def test_backup_download(client):
    response = post(client, "/backup")
    assert response.status_code == 200
    assert response.content.startswith(b"SQLite format 3")
    assert "attachment" in response.headers["content-disposition"]


def test_changing_password_ends_old_sessions(client, store):
    assert client.get("/", follow_redirects=False).status_code == 200
    store.set("совсем-другой-пароль")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/login").status_code == 200  # без зацикливания


# ── программы на Python (Phase 3) ───────────────────────────────────────────


@pytest.fixture
def site_with(fixed_clock):
    """Сайт с выбранной песочницей; вход уже выполнен."""
    from ege_tutor.core.app import TutorApp

    created = []

    def _make(sandbox):
        tutor = TutorApp.create(clock=fixed_clock, sandbox=sandbox)
        created.append(tutor)
        passwords = PasswordStore(web_dir(tutor.settings.data_dir) / "password.argon2")
        passwords.set(PASSWORD)
        app = create_app(tutor, password_store=passwords)
        client = TestClient(app, base_url="https://testserver")
        page = client.get("/login")
        client.post("/login", data={"csrf": _csrf(page.text), "password": PASSWORD, "next": "/"})
        return client, tutor

    yield _make
    for tutor in created:
        tutor.close()


@pytest.fixture
def code_client(site_with):
    """Песочница-заменитель (обычный Python): работает и на Windows."""
    from tests.fakes import LocalSandbox

    return site_with(LocalSandbox())


def test_run_program_on_attempt_page(code_client):
    client, tutor = code_client
    _import_sample(client)
    _review_all(client)
    task = next(t for t in tutor.tasks() if t.exam_item == 17)
    attempt_id = _start(client, task.id)
    page = client.get(f"/attempts/{attempt_id}")
    assert "Запустить программу" in page.text
    assert "2 тест(ов)" in page.text

    wrong = post(client, f"/attempts/{attempt_id}/run", {"code": "print('<b>0</b>')"})
    assert "Неверный вывод на тесте" in wrong.text
    assert "Не прошёл тест №1" in wrong.text
    assert "&lt;b&gt;0&lt;/b&gt;" in wrong.text  # вывод программы не становится HTML

    code = (
        "a = [int(x) for x in open('numbers.txt')]\n"
        "print(sum((x < 0) != (y < 0) for x, y in zip(a, a[1:])))\n"
    )
    good = post(client, f"/attempts/{attempt_id}/run", {"code": code})
    assert "Программа отработала" in good.text
    assert "тесты 2 из 2" in good.text
    assert "Отправить ответ 3" in good.text
    assert "zip(a, a[1:])" in good.text  # последняя программа остаётся в поле

    answered = post(client, f"/attempts/{attempt_id}/answer", {"answer": "3"})
    assert "Итог: верно" in answered.text
    assert len(tutor.code_runs(task.id)) == 2


def test_program_box_only_for_informatics_and_errors(code_client):
    client, tutor = code_client
    _import_sample(client)
    _review_all(client)
    math_task = next(t for t in tutor.tasks() if t.subject.value == "MATH_PROFILE")
    attempt_id = _start(client, math_task.id)
    assert "Запустить программу" not in client.get(f"/attempts/{attempt_id}").text
    refused = post(client, f"/attempts/{attempt_id}/run", {"code": "print(1)"})
    assert "только в задачах по информатике" in refused.text


def test_program_box_explains_missing_sandbox(site_with):
    from ege_tutor.sandbox import UnavailableSandbox

    client, tutor = site_with(UnavailableSandbox("нет Docker"))
    _import_sample(client)
    _review_all(client)
    task = next(t for t in tutor.tasks() if t.exam_item == 17)
    page = client.get(f"/attempts/{_start(client, task.id)}")
    assert "Песочница для программ не настроена" in page.text
    assert "Запустить программу" not in page.text


# ── прогресс, ошибки, повторение (Phase 4) ──────────────────────────────────


def test_progress_mistakes_and_repeat(client, tutor):
    _import_sample(client)
    _review_all(client)
    page = client.get("/progress")
    assert "Пока нет решённых задач" in page.text
    assert "Повторять пока нечего" in client.get("/").text

    task = next(t for t in tutor.tasks() if t.exam_item == 6 and t.subject.value == "MATH_PROFILE")
    attempt_id = _start(client, task.id)
    wrong = post(client, f"/attempts/{attempt_id}/answer", {"answer": "-6"})
    assert "Ошибка записана" in wrong.text and "невнимательность" in wrong.text

    progress = client.get("/progress?subject=MATH_PROFILE")
    assert "<progress" in progress.text and "M06.algebraic" in progress.text
    assert 'style="' not in progress.text  # CSP запрещает inline-стили
    assert client.get("/progress?subject=INFORMATICS").status_code == 200

    mistakes = client.get("/mistakes")
    assert "Частые ошибки" in mistakes.text and "невнимательность" in mistakes.text
    mistake_id = re.search(r'action="/mistakes/(\d+)"', mistakes.text).group(1)
    fixed = post(
        client,
        f"/mistakes/{mistake_id}",
        {"category": "CONDITION", "back": f"/attempts/{attempt_id}"},
    )
    assert str(fixed.url).endswith(f"/attempts/{attempt_id}")
    assert "Причина ошибки уточнена: непонимание условия" in fixed.text
    again = post(
        client, f"/mistakes/{mistake_id}", {"category": "FORMULA", "back": "//evil.example"}
    )
    assert "уже уточнена" in again.text
    assert str(again.url) == "https://testserver/"
    assert "неизвестная причина" in post(client, f"/mistakes/{mistake_id}", {"category": "X"}).text

    home = client.get("/")
    assert "В очереди повторений" in home.text
    repeat = post(client, "/repeat")
    assert "/attempts/" in str(repeat.url)
    assert "Проверить" in repeat.text


def test_repeat_with_empty_queue(client):
    response = post(client, "/repeat")
    assert "очередь повторений пуста" in response.text
