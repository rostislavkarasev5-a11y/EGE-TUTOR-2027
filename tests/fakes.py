"""Заменители портов для тестов."""

import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from ege_tutor.core.domain import (
    AIChatReply,
    AICriterionScore,
    AIError,
    AIMistakeSuggestion,
    AIPart2Suggestion,
    AITaskContext,
    AITaskSuggestion,
    AIText,
    AIUsage,
    ChatTurn,
    SpeechError,
)
from ege_tutor.core.ports.sandbox import RunRequest, RunResult, SandboxVerdict


class LocalSandbox:
    """Запускает программу обычным Python без ограничений. Только для тестов CORE:

    работает и на Windows, где настоящий движок песочницы недоступен.
    """

    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    @property
    def is_available(self) -> bool:
        return True

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in request.files.items():
                (Path(tmp) / name).write_bytes(content)
            done = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", request.code],
                input=request.stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=tmp,
                timeout=30,
                check=False,
            )
        if "SyntaxError" in done.stderr:
            verdict = SandboxVerdict.SYNTAX_ERROR
        elif done.returncode != 0:
            verdict = SandboxVerdict.RUNTIME_ERROR
        else:
            verdict = SandboxVerdict.OK
        return RunResult(verdict, done.stdout, done.stderr, done.returncode, 0.01)


class ScriptedSandbox:
    """Возвращает заранее заданные результаты по очереди."""

    def __init__(self, *results: RunResult, available: bool = True) -> None:
        self.results = list(results)
        self.available = available
        self.requests: list[RunRequest] = []

    @property
    def is_available(self) -> bool:
        return self.available

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        return self.results.pop(0)


def usage(input_tokens: int = 1000, output_tokens: int = 500) -> AIUsage:
    return AIUsage("fake-model", input_tokens, output_tokens, "hash")


class FakeAIService:
    """ИИ для тестов: без интернета и без денег. Ответы задаёт тест, вызовы записываются."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, AITaskContext]] = []
        self.hint_text = "Подумай, какая формула связывает данные величины."
        self.explanation = "Сначала найдём ..., затем ..."
        self.category = "ARITHMETIC"
        self.criteria: tuple[AICriterionScore, ...] = (
            AICriterionScore("Обоснованно получен верный ответ", 2, 2, "всё верно"),
        )
        self.generated: AITaskSuggestion | None = None
        self.chat_text = "Посмотри, как связаны основания степеней."
        self.chat_speech = "Посмотри, как связаны основания степеней."
        self.chat_requests: list[tuple[list[ChatTurn], str, bool]] = []
        self.error: AIError | None = None

    @property
    def is_available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    def _call(self, name: str, task: AITaskContext) -> None:
        self.calls.append((name, task))
        if self.error is not None:
            raise self.error

    def hint(self, task: AITaskContext, level: int, previous: Sequence[str]) -> AIText:
        self._call("hint", task)
        return AIText(self.hint_text, usage())

    def explain(self, task: AITaskContext, student_answer: str | None) -> AIText:
        self._call("explain", task)
        return AIText(self.explanation, usage())

    def classify_mistake(
        self,
        task: AITaskContext,
        student_answer: str | None,
        categories: Sequence[str],
        program_output: str | None,
    ) -> AIMistakeSuggestion:
        self._call("classify_mistake", task)
        return AIMistakeSuggestion(self.category, 0.8, "похоже на ошибку в вычислениях", usage())

    def grade_part2(
        self, task: AITaskContext, solution_text: str, max_points: int
    ) -> AIPart2Suggestion:
        self._call("grade_part2", task)
        return AIPart2Suggestion(self.criteria, "Решение в целом верное.", usage())

    def generate_similar(self, task: AITaskContext) -> AITaskSuggestion:
        self._call("generate_similar", task)
        assert self.generated is not None, "тест должен задать generated"
        return self.generated

    def chat(
        self,
        task: AITaskContext,
        history: Sequence[ChatTurn],
        question: str,
        *,
        finished: bool,
    ) -> AIChatReply:
        self._call("chat", task)
        self.chat_requests.append((list(history), question, finished))
        return AIChatReply(self.chat_text, self.chat_speech, usage())


class FakeSpeechService:
    """Голос для тестов: без интернета и без денег."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.spoken: list[str] = []
        self.heard: list[tuple[int, int]] = []  # (байт, частота)
        self.transcript = "почему здесь логарифм"
        self.error: SpeechError | None = None

    @property
    def is_available(self) -> bool:
        return self.available

    @property
    def unavailable_reason(self) -> str | None:
        return None if self.available else "голос выключен"

    @property
    def voice(self) -> str:
        return "fake-voice"

    def synthesize(self, text: str) -> bytes:
        if self.error is not None:
            raise self.error
        self.spoken.append(text)
        return b"ID3" + text.encode("utf-8")

    def recognize(self, pcm: bytes, sample_rate: int) -> str:
        if self.error is not None:
            raise self.error
        self.heard.append((len(pcm), sample_rate))
        return self.transcript
