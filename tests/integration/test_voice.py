"""Голосовой репетитор (Phase 6.5, ADR-0018): разговор, озвучка, распознавание."""

import pytest

from ege_tutor.config import load_settings
from ege_tutor.core.app import AppError, TutorApp
from ege_tutor.core.domain import (
    AICallStatus,
    AIPurpose,
    AttemptStatus,
    ChatRole,
    SpeechError,
    Subject,
)
from ege_tutor.core.services.assistant import CHAT_REFUSAL
from ege_tutor.core.services.practice import CHAT_HINT_TEXT
from ege_tutor.core.services.voice import speakable
from tests.fakes import FakeAIService, FakeSpeechService, LocalSandbox

TASKS = """
defaults:
  subject: math
  source: USER_MATERIAL
  source_ref: "тест"
tasks:
  - exam_item: 6
    statement: "Решите уравнение 3x − 7 = 11."
    answer: 6
    solution: "3x = 18, x = 6."
    hints: ["Перенеси −7 вправо.", "Получится 3x = 18."]
  - exam_item: 6
    statement: "Решите уравнение 2^x = 1024."
    answer: 10
    solution: "1024 = 2^10."
"""

SECOND = 16_000 * 2  # байт в секунде 16-битной записи 16 кГц


@pytest.fixture
def fake_ai() -> FakeAIService:
    return FakeAIService()


@pytest.fixture
def fake_speech() -> FakeSpeechService:
    return FakeSpeechService()


def _make(fixed_clock, fake_ai, fake_speech, *, budget: float | None = None) -> TutorApp:
    settings = load_settings()
    if budget is not None:
        ai = settings.app.ai.model_copy(update={"monthly_budget_rub": budget})
        settings = settings.model_copy(update={"app": settings.app.model_copy(update={"ai": ai})})
    return TutorApp.create(
        settings=settings,
        clock=fixed_clock,
        ai=fake_ai,
        speech=fake_speech,
        sandbox=LocalSandbox(),
    )


@pytest.fixture
def app(fixed_clock, fake_ai, fake_speech):
    tutor = _make(fixed_clock, fake_ai, fake_speech)
    yield tutor
    tutor.close()


@pytest.fixture
def ids(app, write_file):
    app.import_tasks(write_file("t.yaml", TASKS))
    found = sorted(t.id for t in app.tasks())
    for task_id in found:
        app.review_task(task_id, answer_is_correct=True)
    return found


# ── разговор ────────────────────────────────────────────────────────────────


def test_first_question_counts_as_hint_level_1(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])  # у задачи нет записанных подсказок
    reply = app.ask_tutor(attempt.id, "  с чего   начать? ")
    assert reply.role == ChatRole.TUTOR and reply.text == fake_ai.chat_text
    assert reply.speech == fake_ai.chat_speech
    history, question, finished = fake_ai.chat_requests[0]
    assert (history, question, finished) == ([], "с чего начать?", False)
    assert app.attempt(attempt.id).max_hint_level == 1
    [hint] = app.shown_hints(attempt.id)
    assert (hint.level, hint.text) == (1, CHAT_HINT_TEXT)

    app.ask_tutor(attempt.id, "а дальше?")
    assert app.attempt(attempt.id).max_hint_level == 1  # больше не снижает
    history, _, _ = fake_ai.chat_requests[1]
    assert [(t.from_student, t.text) for t in history] == [
        (True, "с чего начать?"),
        (False, fake_ai.chat_text),
    ]
    roles = [m.role for m in app.chat_messages(attempt.id)]
    assert roles == [ChatRole.STUDENT, ChatRole.TUTOR] * 2


def test_question_opens_recorded_hint_1(app, ids):
    attempt = app.start_attempt(ids[0])  # у задачи записаны подсказки
    app.ask_tutor(attempt.id, "что сделать сначала?")
    [hint] = app.shown_hints(attempt.id)
    assert hint.text == "Перенеси −7 вправо."  # уровень оплачен — подсказка открыта
    assert app.next_hint(attempt.id).level == 2


def test_tutor_knows_attempt_is_running(app, ids, fake_ai):
    # пока попытка идёт, адаптер не кладёт ответ в запрос (проверено в test_yandex_ai)
    attempt = app.start_attempt(ids[1])
    app.ask_tutor(attempt.id, "какой ответ?")
    assert fake_ai.chat_requests[-1][2] is False


def test_reply_revealing_answer_is_replaced(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    fake_ai.chat_text = "Ответ: 10."
    reply = app.ask_tutor(attempt.id, "скажи ответ")
    assert reply.text == CHAT_REFUSAL
    assert app.attempt(attempt.id).max_hint_level == 0  # отказ ничего не стоит ученику
    [call] = app.ai_calls()
    assert (call.purpose, call.status) == (AIPurpose.CHAT, AICallStatus.REJECTED)


def test_after_answer_tutor_may_discuss_it(app, ids, fake_ai):
    attempt = app.start_attempt(ids[1])
    app.submit_answer(attempt.id, "9")
    fake_ai.chat_text = "Верный ответ 10: 1024 = 2^10."
    reply = app.ask_tutor(attempt.id, "почему 10?")
    assert reply.text == fake_ai.chat_text
    assert fake_ai.chat_requests[-1][2] is True
    assert app.attempt(attempt.id).max_hint_level == 0


def test_chat_rules(app, ids):
    attempt = app.start_attempt(ids[1])
    with pytest.raises(AppError, match="напиши вопрос"):
        app.ask_tutor(attempt.id, "   ")
    with pytest.raises(AppError, match="1000"):
        app.ask_tutor(attempt.id, "а" * 1001)
    app.abandon_attempt(attempt.id)
    assert app.attempt(attempt.id).status == AttemptStatus.ABANDONED
    with pytest.raises(AppError, match="брошена"):
        app.ask_tutor(attempt.id, "вопрос")
    assert app.can_chat(attempt.id) is False


def test_no_chat_or_voice_in_diagnostic(app, fake_ai, fake_speech):
    app.install_starter_bank()
    session = app.start_diagnostic(Subject.MATH_PROFILE)
    step = app.diagnostic_step(session.id)
    assert step.attempt is not None
    assert app.can_chat(step.attempt.id) is False
    with pytest.raises(AppError, match="диагностике"):
        app.ask_tutor(step.attempt.id, "подскажи")
    with pytest.raises(AppError, match="диагностике"):
        app.listen(step.attempt.id, b"\0" * SECOND, 16_000)
    assert fake_ai.calls == [] and fake_speech.heard == []


def test_ai_failure_keeps_chat_clean(app, ids, fake_ai):
    from ege_tutor.core.domain import AIError

    attempt = app.start_attempt(ids[1])
    fake_ai.error = AIError("нет связи")
    with pytest.raises(AppError, match="нет связи"):
        app.ask_tutor(attempt.id, "вопрос")
    assert app.chat_messages(attempt.id) == []
    assert app.attempt(attempt.id).max_hint_level == 0


# ── озвучка ─────────────────────────────────────────────────────────────────


def test_speak_chat_is_cached_and_billed_once(app, ids, fake_speech):
    attempt = app.start_attempt(ids[1])
    reply = app.ask_tutor(attempt.id, "с чего начать?")
    first = app.speak_chat(reply.id)
    second = app.speak_chat(reply.id)
    assert first.name == second.name and not first.cached and second.cached
    assert fake_speech.spoken == [reply.speech]
    path = app.speech_clip_path(first.name)
    assert path is not None and path.read_bytes().startswith(b"ID3")
    speech_calls = [c for c in app.ai_calls() if c.purpose == AIPurpose.SPEECH]
    assert len(speech_calls) == 1
    assert speech_calls[0].cost_rub == pytest.approx(
        app.settings.app.speech.tts_cost_rub(len(reply.speech or ""))
    )


def test_speak_hint_and_note(app, ids, fake_speech, fake_ai):
    attempt = app.start_attempt(ids[1])
    fake_ai.hint_text = "Запиши 1024 как 2^k."
    app.ai_hint(attempt.id)
    app.speak_hint(attempt.id, 1)
    assert fake_speech.spoken[-1] == "Запиши 1024 как 2 в степени k."
    with pytest.raises(AppError, match="не открыта"):
        app.speak_hint(attempt.id, 2)
    app.give_up(attempt.id)
    note = app.ai_explain(attempt.id)
    app.speak_note(note.id)
    assert fake_speech.spoken[-1] == speakable(note.text)


def test_clip_names_are_checked(app):
    assert app.speech_clip_path("../app.db") is None
    assert app.speech_clip_path("0" * 32 + ".mp3") is None


def test_speech_error_is_recorded(app, ids, fake_speech):
    attempt = app.start_attempt(ids[1])
    reply = app.ask_tutor(attempt.id, "вопрос")
    fake_speech.error = SpeechError("SpeechKit не принял ключ")
    with pytest.raises(AppError, match="не принял ключ"):
        app.speak_chat(reply.id)
    call = app.ai_calls()[0]
    assert (call.purpose, call.status, call.cost_rub) == (
        AIPurpose.SPEECH,
        AICallStatus.ERROR,
        0.0,
    )


def test_voice_unavailable_without_speech(fixed_clock, fake_ai):
    tutor = _make(fixed_clock, fake_ai, FakeSpeechService(available=False))
    try:
        status = tutor.ai_status()
        assert status.available and not status.speech_available
        assert status.speech_reason == "голос выключен"
    finally:
        tutor.close()


def test_voice_stops_with_budget(fixed_clock, fake_ai, fake_speech):
    tutor = _make(fixed_clock, fake_ai, fake_speech, budget=0)
    try:
        status = tutor.ai_status()
        assert not status.speech_available and "лимит" in (status.speech_reason or "")
    finally:
        tutor.close()


# ── распознавание ───────────────────────────────────────────────────────────


def test_listen(app, ids, fake_speech):
    attempt = app.start_attempt(ids[1])
    text = app.listen(attempt.id, b"\0" * (SECOND * 16), 16_000)
    assert text == fake_speech.transcript
    assert fake_speech.heard == [(SECOND * 16, 16_000)]
    [call] = app.ai_calls()
    assert call.purpose == AIPurpose.LISTEN
    assert call.cost_rub == pytest.approx(2 * app.settings.app.speech.price_stt_per_15s_rub)
    assert app.chat_messages(attempt.id) == []  # текст ученик отправит сам


# В параметрах — длина записи, а не сами байты: иначе имя теста становится огромным,
# и на Windows pytest не может записать его в переменную окружения.
@pytest.mark.parametrize(
    ("size", "rate", "message"),
    [
        (100, 16_000, "короткая"),
        (SECOND * 31, 16_000, "длиннее"),
        (SECOND, 11_025, "частота"),
        (SECOND + 1, 16_000, "повреждена"),
    ],
)
def test_listen_rejects_bad_recordings(app, ids, fake_speech, size, rate, message):
    attempt = app.start_attempt(ids[1])
    with pytest.raises(AppError, match=message):
        app.listen(attempt.id, b"\0" * size, rate)
    assert fake_speech.heard == []


def test_empty_recognition(app, ids, fake_speech):
    attempt = app.start_attempt(ids[1])
    fake_speech.transcript = ""
    with pytest.raises(AppError, match="не разобрана"):
        app.listen(attempt.id, b"\0" * SECOND, 16_000)


# ── текст для чтения вслух ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("x^2 - 4 = 0", "x в квадрате минус 4 равно 0"),
        ("2^(x-1) = 16", "2 в степени (x минус 1) равно 16"),
        ("sqrt(3)*x", "корень из (3) умножить на x"),
        ("log_2(x) ≥ 3", "логарифм по основанию 2 от (x) больше или равно 3"),
        ("какой-то путь 5 км/ч", "какой-то путь 5 км/ч"),
    ],
)
def test_speakable(text, spoken):
    assert speakable(text) == spoken
