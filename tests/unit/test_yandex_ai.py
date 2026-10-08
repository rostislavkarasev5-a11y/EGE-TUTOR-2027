"""Адаптер Yandex AI Studio на поддельном HTTP-сервере: без интернета и без денег (ADR-0017)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ege_tutor.ai import API_KEY_ENV, FOLDER_ENV, DisabledAIService, YandexAIService, make_ai
from ege_tutor.config import ConfigError, load_settings
from ege_tutor.core.domain import AIError, AITaskContext, AnswerType, Subject
from ege_tutor.core.ports import AIService

# Поддельный ключ собирается во время выполнения: в файле нет строки, похожей на секрет.
FAKE_KEY = "test-" + "key-" + "0" * 8
FOLDER = "folder-test"

TASK = AITaskContext(
    subject=Subject.MATH_PROFILE,
    exam_item=6,
    statement="Решите уравнение 2^x = 8.",
    answer_type=AnswerType.NUMBER,
    answer="3",
    solution="8 = 2^3",
)


class _Server:
    """Отвечает заданным кодом и телом, запоминает запросы."""

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], dict]] = []
        self.status = 200
        self.body: dict | str = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                data = json.loads(self.rfile.read(length))
                outer.requests.append(({k.lower(): v for k, v in self.headers.items()}, data))
                raw = outer.body if isinstance(outer.body, str) else json.dumps(outer.body)
                payload = raw.encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reply(self, content: str, usage: dict | None = None) -> None:
        body: dict = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]
        }
        if usage is not None:
            body["usage"] = usage
        self.body = body


@pytest.fixture
def server():
    srv = _Server()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


@pytest.fixture
def ai_config():
    return load_settings().app.ai.model_copy(update={"provider": "yandex", "timeout_seconds": 5})


@pytest.fixture
def service(server, ai_config):
    return YandexAIService(ai_config, FAKE_KEY, FOLDER, base_url=server.url)


def test_request_format_and_headers(server, service):
    server.reply(
        '{"hint": "Запиши 8 как степень двойки."}', {"prompt_tokens": 321, "completion_tokens": 12}
    )
    result = service.hint(TASK, 1, [])
    assert result.text == "Запиши 8 как степень двойки."
    assert (result.usage.input_tokens, result.usage.output_tokens) == (321, 12)
    assert result.usage.model == "yandexgpt/latest"
    [(headers, body)] = server.requests
    assert headers["authorization"] == f"Api-Key {FAKE_KEY}"
    assert headers["openai-project"] == FOLDER
    assert headers["x-data-logging-enabled"] == "false"
    assert body["model"] == f"gpt://{FOLDER}/yandexgpt/latest"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["max_tokens"] == 1500
    user = body["messages"][1]["content"]
    assert TASK.statement in user
    assert "Эталонный ответ" not in user  # в подсказку ответ не отправляется


def test_explain_sends_reference_answer(server, service):
    server.reply('{"explanation": "Так как 8 = 2^3, x = 3."}')
    service.explain(TASK, "4")
    user = server.requests[0][1]["messages"][1]["content"]
    assert "Эталонный ответ: 3" in user and "Ответ ученика: 4" in user


def test_json_inside_code_fence_and_string_token_counts(server, service):
    server.reply(
        '```json\n{"category": "arithmetic", "confidence": 0.7, "explanation": "счёт"}\n```',
        {"prompt_tokens": "100", "completion_tokens": "7"},
    )
    result = service.classify_mistake(TASK, "4", ["ARITHMETIC — арифметика"], None)
    assert result.category == "ARITHMETIC"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 7)


def test_missing_usage_is_estimated_generously(server, service):
    server.reply('{"hint": "Подумай о степенях."}')
    result = service.hint(TASK, 1, ["Первая подсказка"])
    assert result.usage.input_tokens > 100
    assert result.usage.output_tokens > 0
    assert "Первая подсказка" in server.requests[0][1]["messages"][1]["content"]


def test_part2_and_generation_parsing(server, service):
    server.reply(
        json.dumps(
            {
                "criteria": [
                    {"name": "Ответ", "points": 1, "max_points": 2, "comment": "нет отбора"}
                ],
                "summary": "Частично верно.",
            }
        )
    )
    grade = service.grade_part2(TASK, "решение", 2)
    assert grade.criteria[0].points == 1 and grade.summary == "Частично верно."
    server.reply(
        json.dumps({"statement": "3^x = 27", "answer": "3", "solution": "27 = 3^3", "check": "3"})
    )
    made = service.generate_similar(TASK)
    assert (made.statement, made.answer, made.check) == ("3^x = 27", "3", "3")
    assert "выражение" in server.requests[1][1]["messages"][1]["content"]


@pytest.mark.parametrize("content", ["не JSON вовсе", '{"hint": ""}', '{"other": 1}', ""])
def test_bad_answer_is_ai_error_with_usage(server, service, content):
    server.reply(content, {"prompt_tokens": 50, "completion_tokens": 5})
    with pytest.raises(AIError) as info:
        service.hint(TASK, 1, [])
    assert info.value.usage is not None and info.value.usage.input_tokens == 50


def test_wrong_key_message_does_not_leak_key(server, service):
    server.status = 401
    server.body = {"error": {"message": "Unauthorized"}}
    with pytest.raises(AIError, match="не принял ключ") as info:
        service.hint(TASK, 1, [])
    assert FAKE_KEY not in str(info.value)
    assert info.value.usage is None
    assert FAKE_KEY not in repr(service)


def test_server_error_detail(server, service):
    server.status = 400
    server.body = {"error": {"message": "model not found"}}
    with pytest.raises(AIError, match="400: model not found"):
        service.hint(TASK, 1, [])


def test_no_connection(ai_config):
    service = YandexAIService(ai_config, FAKE_KEY, FOLDER, base_url="http://127.0.0.1:9/v1")
    with pytest.raises(AIError, match="нет связи"):
        service.hint(TASK, 1, [])


# ── выбор реализации ────────────────────────────────────────────────────────


def test_make_ai(ai_config):
    disabled = make_ai(load_settings().app.ai, {})
    assert isinstance(disabled, DisabledAIService) and not disabled.is_available
    no_key = make_ai(ai_config, {FOLDER_ENV: FOLDER})
    assert not no_key.is_available
    assert API_KEY_ENV in (no_key.unavailable_reason or "")
    real = make_ai(ai_config, {API_KEY_ENV: FAKE_KEY, FOLDER_ENV: FOLDER})
    assert isinstance(real, YandexAIService) and real.is_available
    for service in (disabled, no_key, real):
        assert isinstance(service, AIService)


def test_disabled_service_refuses():
    with pytest.raises(AIError, match="выключен"):
        DisabledAIService().hint(TASK, 1, [])


def test_env_overrides_ai_settings(monkeypatch):
    monkeypatch.setenv("EGE_AI_PROVIDER", "yandex")
    monkeypatch.setenv("EGE_AI_MONTHLY_BUDGET_RUB", "150")
    monkeypatch.setenv("EGE_AI_MODEL", "yandexgpt-lite/latest")
    ai = load_settings().app.ai
    assert (ai.provider, ai.monthly_budget_rub, ai.model) == (
        "yandex",
        150,
        "yandexgpt-lite/latest",
    )
    monkeypatch.setenv("EGE_AI_PROVIDER", "openai")
    with pytest.raises(ConfigError, match="ИИ"):
        load_settings()


def test_cost_uses_configured_prices():
    ai = load_settings().app.ai
    assert ai.cost_rub(1000, 1000) == pytest.approx(
        ai.price_input_per_1000_rub + ai.price_output_per_1000_rub
    )
