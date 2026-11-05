"""O13 on AP2: the LuCI bridge's own session opens a LuCI page with no password, then leaves nothing behind.

uv run pytest -m hardware tests/hardware/test_ap2_luci.py --router 192.168.1.2 --identity <key> -v

Read-only: the bridge is opened as during a harness run (a read-only rpcd session), the page is only
fetched, and the session is destroyed on close.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from ro_transport import LuciSessionTransport

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.luci_bridge.service import LuciBridgeService
from openwrtgui.luci_bridge.upstream import Upstream, ssh_upstream
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport, ubus_command
from openwrtgui.transport.pool import ConnectionPool

pytestmark = pytest.mark.hardware

PAGE = "admin/network/wireless"
# A pretend run on this PC makes the bridge open the page read-only, as it would during a harness run.
PRETEND_RUN = ProcessInfo(1, ("python.exe", "owg_hardware_test.py"), datetime(2026, 11, 5, 8, 0))


async def test_read_only_session_opens_wireless_page(ap2_luci: LuciSessionTransport, tmp_path: Path) -> None:
    routers = RouterStore(tmp_path / "routers.json")
    rec = RouterRecord(
        id="ap2", name="AP2 · hardware test", host="192.168.1.2", auth="key", added_at=datetime.now()
    )
    routers.upsert(rec)
    guard = BenchGuard(
        GuardWatchList(lock_files=[], processes=["owg_hardware_test.py"]), lister=lambda: [PRETEND_RUN]
    )
    guard.check_local()

    async def factory(_: RouterRecord) -> Transport:
        return ap2_luci

    async def upstream(_: RouterRecord, t: Transport) -> Upstream:
        return await ssh_upstream(t)

    descriptions: dict[str, SelfDescription] = {}
    service = LuciBridgeService(
        pool=ConnectionPool(factory),
        routers=routers,
        guard=guard,
        audit=AuditLog(tmp_path / "audit"),
        descriptions=descriptions,
        upstream_factory=upstream,
    )
    view = await service.open("ap2", PAGE)
    created = next(c for c in ap2_luci.commands if c.startswith("ubus call session create"))
    assert view.access == "read" and created
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            page = await client.get(view.url)
        print(f"\nHTTP {page.status_code}, {len(page.text)} bytes")
        assert page.status_code == 200
        assert 'name="luci_password"' not in page.text, (
            "LuCI showed its login form: the session was not accepted"
        )
    finally:
        await service.close(view.id)
    sid = _session_id(ap2_luci)
    left = await ap2_luci.run(ubus_command("session", "list", {"ubus_rpc_session": sid}))
    assert left.exit_status != 0 or not json.loads(left.stdout or "{}"), (
        f"session {sid} is still there: {left.stdout}"
    )


def _session_id(t: LuciSessionTransport) -> str:
    """The session id the bridge used (the audit hides it; the transport saw it in the grant commands)."""
    grant = next(c for c in t.commands if c.startswith("ubus call session grant "))
    return str(json.loads(grant.split(" ", 4)[4].strip("'"))["ubus_rpc_session"])
