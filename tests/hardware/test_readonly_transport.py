"""The hardware tests' transport wrapper: every probe passes it, and writes never reach the router.

These run in CI on the recorded AP2 output (no hardware marker).
"""

from __future__ import annotations

import pytest
from ro_transport import ReadOnlyTransport

from openwrtgui.probe.describe import describe_router
from openwrtgui.probe.status import read_status
from openwrtgui.transport.fake import ReplayTransport


async def test_probes_pass_the_read_only_wrapper(ap2_transport: ReplayTransport) -> None:
    ro = ReadOnlyTransport(ap2_transport)
    described = await describe_router(ro)
    status = await read_status(ro)
    assert described.identity.board_name == "dlink,dwr-921-c3-uboot"
    assert status.interfaces
    assert len(ro.commands) >= 8


async def test_wrapper_refuses_writes_before_they_run(ap2_transport: ReplayTransport) -> None:
    ro = ReadOnlyTransport(ap2_transport)
    with pytest.raises(AssertionError, match="not read-only"):
        await ro.run("uci set wireless.radio0.disabled=1")
    with pytest.raises(AssertionError, match="stdin"):
        await ro.run_stdin("passwd root", "x\nx\n")
    with pytest.raises(AssertionError, match="shell"):
        await ro.open_shell(80, 24)
    assert ro.commands == []
