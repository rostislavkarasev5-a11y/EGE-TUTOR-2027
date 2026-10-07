import datetime as dt

import pytest

from ege_tutor.ai import DisabledAIService
from ege_tutor.core.clock import FixedClock, SystemClock
from ege_tutor.core.ports import (
    AIService,
    Clock,
    RunRequest,
    Sandbox,
    SandboxLimits,
    SandboxUnavailableError,
)
from ege_tutor.sandbox import UnavailableSandbox


def test_default_adapters_satisfy_ports():
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FixedClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)), Clock)
    assert isinstance(DisabledAIService(), AIService)
    assert isinstance(UnavailableSandbox(), Sandbox)


def test_disabled_ai_is_not_available():
    assert DisabledAIService().is_available is False


def test_unavailable_sandbox_refuses_to_run():
    sandbox = UnavailableSandbox()
    request = RunRequest(code="print(1)", limits=SandboxLimits(10, 256))
    assert sandbox.is_available is False
    with pytest.raises(SandboxUnavailableError, match="Phase 3"):
        sandbox.run(request)


def test_sandbox_network_is_off_by_default():
    assert SandboxLimits(10, 256).network_enabled is False


def test_system_clock_is_timezone_aware():
    assert SystemClock().now().tzinfo is not None


def test_fixed_clock_requires_timezone():
    with pytest.raises(ValueError):
        FixedClock(dt.datetime(2026, 1, 1))


def test_fixed_clock_advances(fixed_clock):
    start = fixed_clock.today()
    fixed_clock.advance(dt.timedelta(days=3))
    assert (fixed_clock.today() - start).days == 3
