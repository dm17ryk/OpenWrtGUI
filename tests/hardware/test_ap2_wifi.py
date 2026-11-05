"""AP2 radio-on window: Apply puts exactly the asked modes on air (proven by beacons), then AP2 is restored.

uv run pytest -m hardware tests/hardware/test_ap2_wifi.py --router 192.168.1.2 --identity <key> \
    --allow-writes --txctl-told -v

Run it only inside a window the txctl session has agreed to (SSID, channel 6, at most 30 minutes). The
radio goes on air with the test SSID below, and the test always ends by writing back the exact
/etc/config/wireless it found and reloading the radio, then checks the lab options and that it is parked.
While on air it records tests/fixtures/ap2/wifi_on.json (the RF set, the beacon capture, minstrel rates).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import SshTransport
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest, SsidRequest, TxPowerSetting
from openwrtgui.wifi.parse import parse_iw_dev, parse_uci_show
from openwrtgui.wifi.service import MONITOR, ApplyResult, WifiService

pytestmark = pytest.mark.hardware

ROOT = Path(__file__).resolve().parents[2]
WIFI_ON = ROOT / "tests" / "fixtures" / "ap2" / "wifi_on.json"
TEST_SSID = "OwgTest"  # not a run SSID, so no harness station joins and Bench Guard stays quiet
CONFIG = "/etc/config/wireless"
LAB = {
    "wireless.radio0.country": "IL",
    "wireless.radio0.legacy_rates": "1",
    "wireless.radio0.cell_density": "0",
}


def _recorder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", ROOT / "tools" / "record_fixtures.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


def _service(t: SshTransport, tmp_path: Path) -> WifiService:
    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(
        RouterRecord(
            id="ap2", name="AP2 · hardware test", host="192.168.1.2", auth="key", added_at=datetime.now()
        )
    )

    async def factory(_: RouterRecord) -> Transport:
        return t

    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    return WifiService(
        pool=ConnectionPool(factory),
        routers=routers,
        guard=guard,
        audit=AuditLog(tmp_path / "audit"),
        descriptions=descriptions,
        statuses=statuses,
    )


def _proven(result: ApplyResult, beacon: str) -> None:
    failed = [f"{c.name}: {c.detail}" for c in result.checks if not c.ok]
    assert result.applied and result.verified and not failed, failed or result.error
    detail = next(c.detail for c in result.checks if c.name == "beacon rate")
    assert detail.startswith(beacon), detail


async def _record_on_air(t: SshTransport) -> None:
    rf = _recorder()
    recorded = await rf.run_set(t, await rf.wifi_on_commands(t))
    ap = next(i for i in parse_iw_dev((await t.run("iw dev")).stdout) if i.phy == 0 and i.type == "AP")
    capture = [
        f"iw phy phy0 interface add {MONITOR} type monitor && ip link set {MONITOR} up",
        f"timeout 5 tcpdump -i {MONITOR} -e -n -c 5 -l 'type mgt subtype beacon and wlan addr2 {ap.addr}'",
    ]
    try:
        recorded |= await rf.run_set(t, tuple(capture))
    finally:
        await t.run(f"ip link del {MONITOR}")
    WIFI_ON.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(recorded)} commands to {WIFI_ON}")


async def _restore(t: SshTransport, snapshot: str) -> None:
    await t.run("uci revert wireless")
    wrote = await t.run_stdin(f"cat > {CONFIG}", snapshot)
    assert wrote.ok, wrote.stderr
    await t.run("wifi down radio0; wifi up radio0", timeout=60.0)


async def test_apply_verify_record_restore(ap2_rw: SshTransport, tmp_path: Path) -> None:
    t = ap2_rw
    snapshot = (await t.run(f"cat {CONFIG}")).stdout
    before = (await t.run("uci -q show wireless")).stdout
    assert parse_uci_show(before).get("wireless.radio0.disabled") == "1", (
        "AP2's radio must be parked before the window"
    )
    service = _service(t, tmp_path)
    try:
        n20 = RadioRequest(
            radio="radio0",
            modes=ModeSelection("set", frozenset({"n20"})),
            channels=ChannelSelection("set", frozenset({6})),
            txpower=TxPowerSetting("auto"),
            ssids=(SsidRequest(section="default_radio0", ssid=TEST_SSID),),
        )
        _proven(await service.apply("ap2", n20), "6.0")
        await _record_on_air(t)
        _proven(
            await service.apply(
                "ap2", RadioRequest(radio="radio0", modes=ModeSelection("set", frozenset({"g"})))
            ),
            "6.0",
        )
        _proven(
            await service.apply(
                "ap2", RadioRequest(radio="radio0", modes=ModeSelection("set", frozenset({"b"})))
            ),
            "1.0",
        )
    finally:
        await _restore(t, snapshot)
    after = (await t.run("uci -q show wireless")).stdout
    assert after == before
    uci = parse_uci_show(after)
    assert {k: uci.get(k) for k in LAB} == LAB
    ifaces = parse_iw_dev((await t.run("iw dev")).stdout)
    assert not any(i.ifname == MONITOR for i in ifaces), "monitor interface left behind"
    assert not any(i.phy == 0 and i.type == "AP" for i in ifaces), "radio0 still on air after the restore"
