from __future__ import annotations

import logging
import signal
import sys

import pytest
from starlette.applications import Starlette

from openwrtgui.luci_bridge.server import serve


async def test_loopback_servers_leave_the_app_signal_handlers_alone() -> None:
    before = signal.getsignal(signal.SIGINT)
    _, stop_a = await serve(Starlette())
    _, stop_b = await serve(Starlette())
    assert signal.getsignal(signal.SIGINT) is before
    await stop_a()  # out of order: A opened first, closes first
    await stop_b()
    assert signal.getsignal(signal.SIGINT) is before


async def test_starts_without_a_console_and_leaves_logging_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    # the windowed exe has no console: sys.stdout and sys.stderr are None (packaging/OpenWrtGUI.spec)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    loggers = [logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")]
    before = [(lg.handlers[:], lg.propagate, lg.level) for lg in loggers]
    _, stop = await serve(Starlette())
    await stop()
    assert [(lg.handlers[:], lg.propagate, lg.level) for lg in loggers] == before
