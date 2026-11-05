from __future__ import annotations

import signal

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
