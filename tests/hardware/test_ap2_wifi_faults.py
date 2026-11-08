"""AP2 Wi-Fi faults on air (spec O16): Block for N s, Deauth and AP down sent to a real station, then AP2 is
restored.

uv run pytest -m hardware tests/hardware/test_ap2_wifi_faults.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told --adb-station <serial> -v -s

Run it only in a radio window the txctl session agreed to (OwgTest, channel 6, at most 15 minutes), with the
phone's owner told. The radio goes on air with a key made for this run, so only the phone joins; it joins over
adb (`cmd wifi connect-network`) and forgets the network at the end. The test always writes back the exact
/etc/config/wireless it found, reloads the radio and checks it is parked; `fw_window` then checks the
firewall, nft tables, qdiscs, /tmp/owg and the switch ports are as found.
"""

from __future__ import annotations

import asyncio
import secrets
import subprocess

import pytest

from conftest import FwWindow
from openwrtgui.faults.model import FaultRequest, FaultTarget, TargetRef
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.transport.ssh import SshTransport
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest, SsidRequest, TxPowerSetting
from openwrtgui.wifi.parse import parse_iw_dev, parse_uci_show
from openwrtgui.wifi.service import MONITOR

pytestmark = pytest.mark.hardware

AP2 = "ap2"
TEST_SSID = "OwgTest"  # not a run SSID, so no harness station joins and Bench Guard stays quiet
CONFIG = "/etc/config/wireless"
PARK_WAIT_S = 20
JOIN_WAIT_S = 90
BAN_S = 30
AP_DOWN_S = 10
LAB = {
    "wireless.radio0.country": "IL",
    "wireless.radio0.legacy_rates": "1",
    "wireless.radio0.cell_density": "0",
}


class AdbStation:
    """The phone, joined to the test SSID over adb. The key is on adb's command line only, never in output."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.enabled_wifi = False

    def _shell(self, *args: str) -> str:
        done = subprocess.run(
            ["adb", "-s", self.serial, "shell", "cmd", "wifi", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if done.returncode != 0:
            raise RuntimeError(f"adb cmd wifi {args[0]} failed ({done.returncode})")
        return done.stdout

    async def join(self, ssid: str, key: str) -> None:
        if "Wifi is disabled" in await asyncio.to_thread(self._shell, "status"):
            await asyncio.to_thread(self._shell, "set-wifi-enabled", "enabled")
            self.enabled_wifi = True
        await asyncio.to_thread(self._shell, "connect-network", ssid, "wpa2", key)

    async def forget(self, ssid: str) -> None:
        listed = await asyncio.to_thread(self._shell, "list-networks")
        for line in listed.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1] == ssid:
                await asyncio.to_thread(self._shell, "forget-network", parts[0])
        if self.enabled_wifi:
            await asyncio.to_thread(self._shell, "set-wifi-enabled", "disabled")


def _proven(result: NetApplyResult) -> None:
    print([(c.name, c.ok, c.detail) for c in result.checks], result.error)
    failed = [f"{c.name}: {c.detail}" for c in result.checks if c.ok is not True]
    assert result.applied and result.verified, failed or result.error


async def _arm(w: FwWindow, req: FaultRequest) -> NetApplyResult:
    plan = await w.faults.plan_fault(AP2, req)
    print("\n" + "\n".join(plan.lines))
    return await w.faults.apply_fault(AP2, req, plan.digest)


async def _clients(t: Transport, ifname: str) -> set[str]:
    clients = (await ubus_call(t, f"hostapd.{ifname}", "get_clients") or {}).get("clients", {})
    return {k.lower() for k in clients}


async def _station(w: FwWindow, phone: AdbStation, key: str) -> FaultTarget:
    """The one station of the test SSID (its key was made for this run, so it is the phone)."""
    for second in range(JOIN_WAIT_S):
        on_air = [x for x in (await w.faults.state(AP2)).targets if x.via not in (None, "wired")]
        if len(on_air) == 1:
            return on_air[0]
        assert len(on_air) < 2, f"more than one station on {TEST_SSID}: {on_air}"
        if second and second % 30 == 0:
            await phone.join(TEST_SSID, key)  # Android waits longer after rejected joins; ask again
        await asyncio.sleep(1)
    pytest.fail(f"no station joined {TEST_SSID} in {JOIN_WAIT_S} s")


async def _on_air(t: Transport) -> bool:
    return any(i.phy == 0 and i.type == "AP" for i in parse_iw_dev((await t.run("iw dev")).stdout))


async def _restore(t: SshTransport, snapshot: str) -> None:
    await t.run("uci revert wireless")
    wrote = await t.run_stdin(f"cat > {CONFIG}", snapshot)
    assert wrote.ok, wrote.stderr
    await t.run("wifi down radio0; wifi up radio0", timeout=60.0)
    for _ in range(PARK_WAIT_S):  # netifd takes the AP interface down about a second after `wifi` returns
        if not await _on_air(t):
            return
        await asyncio.sleep(1)


async def test_wifi_faults_on_air(fw_window: FwWindow, request: pytest.FixtureRequest) -> None:
    serial = request.config.getoption("--adb-station")
    if not serial:
        pytest.skip("pass --adb-station <serial> of the phone that joins the test SSID")
    phone = AdbStation(serial)
    t = await fw_window.connect()
    snapshot = (await t.run(f"cat {CONFIG}")).stdout
    before = (await t.run("uci -q show wireless")).stdout
    key = secrets.token_urlsafe(16)
    try:
        await _faults_on_air(fw_window, t, phone, key)
    finally:
        try:
            await phone.forget(TEST_SSID)
        finally:
            await _restore(t, snapshot)
    try:
        after = (await t.run("uci -q show wireless")).stdout
        assert after == before
        uci = parse_uci_show(after)
        assert {k: uci.get(k) for k in LAB} == LAB
        assert not any(i.ifname == MONITOR for i in parse_iw_dev((await t.run("iw dev")).stdout))
        assert not await _on_air(t), f"radio0 still on air {PARK_WAIT_S} s after the restore"
    finally:
        await t.close()


async def _faults_on_air(w: FwWindow, t: Transport, phone: AdbStation, key: str) -> None:
    on = await w.wifi.apply(
        AP2,
        RadioRequest(
            radio="radio0",
            modes=ModeSelection("set", frozenset({"n20"})),
            channels=ChannelSelection("set", frozenset({6})),
            txpower=TxPowerSetting("auto"),
            ssids=(SsidRequest(section="default_radio0", ssid=TEST_SSID, key=key),),
        ),
    )
    assert on.applied and on.verified, [f"{c.name}: {c.detail}" for c in on.checks if not c.ok] or on.error
    await phone.join(TEST_SSID, key)

    # Block for 30 s: hostapd lists the ban and keeps the phone out, then lifts the ban on time
    station = await _station(w, phone, key)
    assert station.mac and station.via
    print(f"\nstation {station.mac} on {station.via}")
    _proven(await _arm(w, FaultRequest("ban", TargetRef(station.mac, None), ban_s=BAN_S)))
    for _ in range(10):
        assert station.mac not in await _clients(t, station.via), "joined while banned"
        await asyncio.sleep(2)
    await asyncio.sleep(BAN_S - 15)  # about 35 s after the ban
    bans = await ubus_call(t, f"hostapd.{station.via}", "list_bans")
    assert station.mac not in str(bans).lower(), bans
    assert (await w.faults.state(AP2)).armed == ()

    # Deauth: the phone leaves at once, and may join again
    station = await _station(w, phone, key)
    assert station.mac
    _proven(await _arm(w, FaultRequest("deauth", TargetRef(station.mac, None))))

    # AP down held 10 s: hostapd stops the BSS, the router's timer starts it again
    station = await _station(w, phone, key)
    assert station.mac and station.via
    _proven(await _arm(w, FaultRequest("ap_down", TargetRef(station.mac, None), hold_s=AP_DOWN_S)))
    await w.pool.close_all()  # the app goes away; the router's timer brings the BSS back
    await asyncio.sleep(AP_DOWN_S + 5)
    shown = await t.run(f"hostapd_cli -i {station.via} status")
    assert "state=ENABLED" in shown.stdout, shown.stdout
    assert (await w.faults.state(AP2)).armed == ()
    await _station(w, phone, key)
