"""AP2 Wi-Fi faults on air (spec O16): Block for N s, Deauth and AP down sent to a real station, then AP2 is
restored.

uv run pytest -m hardware tests/hardware/test_ap2_wifi_faults.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told --adb-station <serial> [--o16-channel 11] -v -s

Run it only in a radio window the txctl session agreed to (OwgTest, channel 6 or the --o16-channel agreed
with whoever measures on the bench, at most 15 minutes), with the phone's owner at hand. The radio goes on
air with a key made for this run, so only the phone joins. The phone runs a user build, where
`cmd wifi connect-network` is root-only, so the test gives it the SSID as a network suggestion over adb; the
first time, the owner unlocks the phone and taps Allow on its suggested-networks prompt for Shell (the
approval stays). The suggestion is removed at the end. The test always writes back the exact
/etc/config/wireless it found, reloads the radio and checks it is parked; `fw_window` then checks the
firewall, nft tables, qdiscs, /tmp/owg and the switch ports are as found.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
from collections.abc import Awaitable, Callable

import pytest

from conftest import FwWindow, wireless_snapshot
from openwrtgui.faults.model import FaultRequest, FaultTarget, TargetRef
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.transport.ssh import SshTransport
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest, SsidRequest, TxPowerSetting
from openwrtgui.wifi.parse import parse_iw_dev, parse_iw_dev_info, parse_uci_show
from openwrtgui.wifi.service import MONITOR

pytestmark = pytest.mark.hardware

AP2 = "ap2"
TEST_SSID = "OwgTest"  # not a run SSID, so no harness station joins and Bench Guard stays quiet
CONFIG = "/etc/config/wireless"
PARK_WAIT_S = 20
APPROVE_WAIT_S = 240  # the first join waits for the owner to unlock the phone and tap Allow
JOIN_WAIT_S = 90
SCAN_EVERY_S = 10
BAN_S = 30
AP_DOWN_S = 10
LAB = {
    "wireless.radio0.country": "IL",
    "wireless.radio0.legacy_rates": "1",
    "wireless.radio0.cell_density": "0",
}


class _Hidden(str):
    """The run's Wi-Fi key: pytest prints a failing frame's locals, so its repr must not show it."""

    def __repr__(self) -> str:
        return "'<hidden>'"


class AdbStation:
    """The phone, given the test SSID as a network suggestion over adb (`cmd wifi add-suggestion`); it joins
    on its own once its owner has allowed Shell's suggestions. The key is on adb's command line only, never
    in output."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.enabled_wifi = False
        self.suggested = False

    def _shell(self, *args: str, check: bool = True) -> str:
        done = subprocess.run(
            ["adb", "-s", self.serial, "shell", "cmd", "wifi", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if check and done.returncode != 0:
            raise RuntimeError(f"adb cmd wifi {args[0]} failed ({done.returncode})")
        return done.stdout

    async def join(self, ssid: str, key: str) -> None:
        # A shell suggestion of that name that this run did not add is someone else's: never replace or
        # remove it
        if ssid in await asyncio.to_thread(self._shell, "list-suggestions"):
            raise RuntimeError(f"the phone already has a shell suggestion for {ssid}; not touching it")
        if "Wifi is disabled" in await asyncio.to_thread(self._shell, "status"):
            await asyncio.to_thread(self._shell, "set-wifi-enabled", "enabled")
            self.enabled_wifi = True
        await asyncio.to_thread(self._shell, "add-suggestion", ssid, "wpa2", key)
        self.suggested = True

    async def scan(self) -> None:
        """Ask for a scan now. Best effort: Android may throttle it, and the phone scans on its own anyway."""
        await asyncio.to_thread(self._shell, "start-scan", check=False)

    async def rejoin(self) -> None:
        """Wi-Fi off and on: Android keeps away for minutes from an AP that turned it down, and Wi-Fi off
        clears that."""
        await asyncio.to_thread(self._shell, "set-wifi-enabled", "disabled")
        await asyncio.sleep(3)
        await asyncio.to_thread(self._shell, "set-wifi-enabled", "enabled")

    async def forget(self, ssid: str) -> None:
        if self.suggested:
            await asyncio.to_thread(self._shell, "remove-suggestion", ssid)
            self.suggested = False
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


async def _associated(t: Transport, ifname: str) -> set[str]:
    """The stations hostapd has associated. A deauthenticated one stays listed, no longer associated, for
    about a second (AP2, 2026-11-09: the phone was still listed right after the ban)."""
    clients = (await ubus_call(t, f"hostapd.{ifname}", "get_clients") or {}).get("clients", {})
    return {k.lower() for k, v in clients.items() if isinstance(v, dict) and v.get("assoc")}


async def _test_bss(t: Transport) -> str:
    """The AP interface that serves the test SSID: the faults go only to its stations."""
    for iface in parse_iw_dev((await t.run("iw dev")).stdout):
        if iface.phy == 0 and iface.type == "AP":
            info = parse_iw_dev_info((await t.run(f"iw dev {iface.ifname} info")).stdout)
            if info.ssid == TEST_SSID:
                return iface.ifname
    pytest.fail(f"no AP interface on radio0 serves {TEST_SSID}")


async def _station(w: FwWindow, phone: AdbStation, bss: str, wait_s: int = JOIN_WAIT_S) -> FaultTarget:
    """The one station of the test SSID's interface (its key was made for this run, so it is the phone);
    clients of any other interface are never picked."""
    for second in range(wait_s):
        on_air = [x for x in (await w.faults.state(AP2)).targets if x.via == bss]
        if len(on_air) == 1:
            return on_air[0]
        assert len(on_air) < 2, f"more than one station on {TEST_SSID}: {on_air}"
        if second % SCAN_EVERY_S == 0:
            await phone.scan()
        await asyncio.sleep(1)
    pytest.fail(f"no station joined {TEST_SSID} in {wait_s} s")


async def _on_air(t: Transport) -> bool:
    return any(i.phy == 0 and i.type == "AP" for i in parse_iw_dev((await t.run("iw dev")).stdout))


async def _uci_wireless(t: Transport) -> str:
    shown = await t.run("uci -q show wireless")
    assert shown.ok, f"uci show wireless failed (exit {shown.exit_status})"
    return shown.stdout


async def _netifd_radio(t: Transport) -> str:
    """netifd's view of radio0 for the log: its state and interface names only, never the config (the key)."""
    status = await t.run("ubus call network.wireless status")
    try:
        radio = json.loads(status.stdout or "{}").get("radio0", {})
    except ValueError:
        return f"unreadable (exit {status.exit_status})"
    state = {k: radio.get(k) for k in ("up", "pending", "autostart", "disabled", "retry_setup_failed")}
    names = [i.get("ifname") for i in radio.get("interfaces", []) if isinstance(i, dict)]
    return f"{state} interfaces={names}"


async def _park(
    t: Transport, *, waits: int = PARK_WAIT_S, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> int:
    """Reload radio0 with the parked config and wait for netifd to take the AP interface down: the passes
    it took, 0 when it is still on air. HW-2 (2026-11-13): after the owgmon0 test the interface was still up
    20 s after `wifi down radio0; wifi up radio0`; then netifd's view is printed and radio0 goes down and up
    once more, apart."""
    for attempt in (1, 2):
        if attempt == 1:
            await t.run("wifi down radio0; wifi up radio0", timeout=60.0)
        else:
            print(f"\nradio0 still on air after the restore; netifd: {await _netifd_radio(t)}")
            await t.run("wifi down radio0", timeout=60.0)
            await sleep(2)
            await t.run("wifi up radio0", timeout=60.0)
        for _ in range(waits):  # netifd takes the AP interface down about a second after `wifi` returns
            if not await _on_air(t):
                return attempt
            await sleep(1)
    return 0


async def _restore(t: SshTransport, snapshot: str) -> int:
    """Write AP2's wireless config back as found and park radio0: the passes `_park` took (0: on air)."""
    await t.run("uci revert wireless")
    wrote = await t.run_stdin(f"cat > {CONFIG}", snapshot)
    assert wrote.ok, wrote.stderr
    return await _park(t)


async def test_wifi_faults_on_air(fw_window: FwWindow, request: pytest.FixtureRequest) -> None:
    serial = request.config.getoption("--adb-station")
    if not serial:
        pytest.skip("pass --adb-station <serial> of the phone that joins the test SSID")
    phone = AdbStation(serial)
    t = await fw_window.connect()
    try:
        snapshot = await wireless_snapshot(t)  # checked before anything changes: the restore writes it back
        before = await _uci_wireless(t)
        key = _Hidden(secrets.token_urlsafe(16))
        try:
            await _faults_on_air(fw_window, t, phone, key, request.config.getoption("--o16-channel"))
        finally:
            try:
                await phone.forget(TEST_SSID)
            finally:
                await _restore(t, snapshot)
        after = await _uci_wireless(t)
        if after != before:  # not an assert: pytest would print both, AP2's own key included
            pytest.fail("AP2's wireless config is not as found after the restore")
        uci = parse_uci_show(after)
        assert {k: uci.get(k) for k in LAB} == LAB
        assert not any(i.ifname == MONITOR for i in parse_iw_dev((await t.run("iw dev")).stdout))
        assert not await _on_air(t), f"radio0 still on air {PARK_WAIT_S} s after the restore"
    finally:
        await t.close()


async def _faults_on_air(w: FwWindow, t: Transport, phone: AdbStation, key: str, channel: int) -> None:
    on = await w.wifi.apply(
        AP2,
        RadioRequest(
            radio="radio0",
            modes=ModeSelection("set", frozenset({"n20"})),
            channels=ChannelSelection("set", frozenset({channel})),
            txpower=TxPowerSetting("auto"),
            ssids=(SsidRequest(section="default_radio0", ssid=TEST_SSID, key=key),),
        ),
    )
    assert on.applied and on.verified, [f"{c.name}: {c.detail}" for c in on.checks if not c.ok] or on.error
    bss = await _test_bss(t)
    await phone.join(TEST_SSID, key)
    print(f"\nwaiting {APPROVE_WAIT_S} s for the phone: unlock it, tap Allow on the suggestions prompt")

    # Block for 30 s: hostapd lists the ban and keeps the phone out, then lifts the ban on time
    station = await _station(w, phone, bss, APPROVE_WAIT_S)
    assert station.mac and station.via
    print(f"\nstation {station.mac} on {station.via}")
    _proven(await _arm(w, FaultRequest("ban", TargetRef(station.mac, None), ban_s=BAN_S)))
    for _ in range(10):
        assert station.mac not in await _associated(t, station.via), "joined while banned"
        await asyncio.sleep(2)
    await asyncio.sleep(BAN_S - 15)  # about 35 s after the ban
    bans = await ubus_call(t, f"hostapd.{station.via}", "list_bans")
    assert station.mac not in str(bans).lower(), bans
    assert (await w.faults.state(AP2)).armed == ()

    # Deauth: the phone leaves at once, and may join again
    await phone.rejoin()  # the ban turned the phone down; Android would keep away from AP2 for minutes
    station = await _station(w, phone, bss)
    assert station.mac
    _proven(await _arm(w, FaultRequest("deauth", TargetRef(station.mac, None))))

    # AP down held 10 s: hostapd stops the BSS, the router's timer starts it again
    station = await _station(w, phone, bss)
    assert station.mac and station.via
    _proven(await _arm(w, FaultRequest("ap_down", TargetRef(station.mac, None), hold_s=AP_DOWN_S)))
    await w.pool.close_all()  # the app goes away; the router's timer brings the BSS back
    await asyncio.sleep(AP_DOWN_S + 5)
    shown = await t.run(f"hostapd_cli -i {station.via} status")
    assert "state=ENABLED" in shown.stdout, shown.stdout
    assert (await w.faults.state(AP2)).armed == ()
    await _station(w, phone, bss)
