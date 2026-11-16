"""v1.0a1/a2 on real AP2, read only: the LuCI page list (the pages LuCI hides, Realtime > Wireless -> RF live)
and the Plugins, Mount points and Legacy iptables reads. Every command goes through ReadOnlyTransport.

uv run pytest -m hardware tests/hardware/test_ap2_v10a_reads.py --router 192.168.1.2 --identity <key> \
    --known-hosts <known_hosts> -v -s
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from ro_transport import ReadOnlyTransport

from openwrtgui.fw.iptables_service import IptablesService
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.luci_bridge.service import LuciBridgeService
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.system.fstab_service import FstabService
from openwrtgui.system.plugins_service import PluginsService
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"
HIDDEN = {
    "admin/network/firewall/custom",
    "admin/network/switch-vlan",
    "admin/status/iptables",
    "admin/status/routes",
    "admin/system/mounts",
}


def _no_upstream(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("this read-only check opens no LuCI page")


@pytest.fixture
async def services(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    identity: Path = request.config.getoption("--identity")
    host_keys = HostKeyStore(request.config.getoption("--known-hosts"))
    opened: list[ReadOnlyTransport] = []

    async def factory(rec: RouterRecord) -> Transport:
        guard_state = BenchGuard(GuardWatchList()).check_local()
        if guard_state.live:
            pytest.skip("Bench Guard sees a run: " + "; ".join(r.text for r in guard_state.reasons))
        inner = await SshTransport.connect(AP2, 22, "root", host_keys=host_keys, key_paths=[identity])
        t = ReadOnlyTransport(inner)
        opened.append(t)
        return t

    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    descriptions: dict[str, SelfDescription] = {}
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    luci = LuciBridgeService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        descriptions=descriptions,
        upstream_factory=_no_upstream,
    )
    try:
        yield {
            "luci": luci,
            "plugins": PluginsService(pool=pool, routers=routers, runner=runner),
            "fstab": FstabService(pool=pool, routers=routers, runner=runner),
            "iptables": IptablesService(pool=pool, routers=routers, runner=runner),
            "opened": opened,
        }
    finally:
        await pool.close_all()


async def test_the_luci_page_list_on_ap2(services: Any) -> None:
    pages = {p.path: p for p in await services["luci"].pages("ap2")}
    hidden = {path for path, p in pages.items() if not p.available}
    print("\nhidden (Not on this router):")
    for path in sorted(hidden):
        print(
            f"  {pages[path].label}  [{path}]  missing: {pages[path].missing}  checked: {pages[path].checked}"
        )
    assert hidden == HIDDEN
    assert all(pages[p].checked for p in HIDDEN), "AP2's facts must be read, not assumed"
    wireless = pages["admin/status/realtime/wireless"]
    print(
        f"Realtime > Wireless: available {wireless.available}, opens {wireless.native} (tab {wireless.tab})"
    )
    assert (wireless.available, wireless.native) == (True, "rf")
    fallback = [p.label for p in pages.values() if p.available and p.native is None]
    print(f"Open in LuCI (no screen here): {fallback}")
    assert fallback == []  # every page of the bench image has a screen here (v1.0a2)


async def test_plugins_mounts_and_iptables_read(services: Any) -> None:
    plugins = await services["plugins"].state("ap2")
    print(f"\nplugins: {plugins.model_dump()}")
    fstab = await services["fstab"].state("ap2")
    print(f"mount points: {fstab.model_dump()}")
    iptables = await services["iptables"].state("ap2")
    print(f"iptables: {iptables.model_dump()}")
    assert not fstab.block  # no block-mount on the bench image: read only
    commands = [c for t in services["opened"] for c in t.commands]
    print(f"{len(commands)} read-only commands, none refused")
