"""Read-only checks on AP2 against the real router. Opt-in: pytest -m hardware (see conftest.py)."""

from __future__ import annotations

import pytest
from ro_transport import ReadOnlyTransport

from openwrtgui.probe.describe import describe_router, propose_port_labels
from openwrtgui.probe.status import read_status

pytestmark = pytest.mark.hardware


async def test_ap2_describes_itself(ap2: ReadOnlyTransport) -> None:
    d = await describe_router(ap2)
    assert d.identity.board_name == "dlink,dwr-921-c3-uboot"
    assert propose_port_labels(d.board)[0] == "LAN4"
    assert d.luci is not None
    assert d.luci.menu_entries > 0


async def test_ap2_status_reads(ap2: ReadOnlyTransport) -> None:
    s = await read_status(ap2)
    assert any(i.name == "lan" and i.up for i in s.interfaces)
