"""The simulated modem's faults: a session up without a packet-data handle (wedged), and stale QMI client
state that keeps `ifup lte` from starting a session until `uqmi --sync`."""

from __future__ import annotations

import json
from typing import Any

from openwrtgui.context import AppContext
from openwrtgui.transport.fake import ReplayTransport

DEV = "/dev/cdc-wdm0"
LOW = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode low_power"
ONLINE = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode online"
SYNC = f"uqmi -s -d {DEV} -t 5000 --sync"
AUTOCONNECT_OFF = f"uqmi -s -d {DEV} -t 5000 --set-autoconnect disabled"
STATUS = "ubus call network.interface.lte status"


async def _transport(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t


async def _status(t: ReplayTransport) -> dict[str, Any]:
    result = await t.run(STATUS)
    assert result.ok, result.stderr
    status: dict[str, Any] = json.loads(result.stdout)
    return status


async def test_a_wedged_modem_comes_up_without_a_handle(ctx: AppContext) -> None:
    t = await _transport(ctx)
    t.state.modem.wedged = True  # type: ignore[union-attr]
    assert (await t.run("ifup lte")).ok
    status = await _status(t)
    assert status["up"] is True
    assert status["data"]["pdh_4"] == "0xffffffff"


async def test_a_modem_restart_clears_the_wedge(ctx: AppContext) -> None:
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.wedged = True
    for line in (LOW, ONLINE, "ifup lte"):
        assert (await t.run(line)).ok, line
    status = await _status(t)
    assert status["data"]["pdh_4"] == "90215808"
    assert modem.wedged is False


async def test_stale_qmi_blocks_ifup_until_sync(ctx: AppContext) -> None:
    t = await _transport(ctx)
    t.state.modem.stale_qmi = True  # type: ignore[union-attr]
    await t.run("ifdown lte")
    await t.run("ifup lte")
    assert (await _status(t))["up"] is False
    synced = await t.run(SYNC)
    assert (synced.exit_status, synced.stdout) == (0, "")
    await t.run("ifup lte")
    assert (await _status(t))["up"] is True


async def test_modem_autoconnect_blocks_ifup_until_turned_off(ctx: AppContext) -> None:
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.autoconnect_on = True
    modem.autoconnect_refusals = 1
    await t.run("ifdown lte")
    await t.run("ifup lte")
    assert (await _status(t))["up"] is False
    refused = await t.run(AUTOCONNECT_OFF)
    assert refused.exit_status == 1 and modem.autoconnect_on
    taken = await t.run(AUTOCONNECT_OFF)
    assert (taken.exit_status, taken.stdout) == (0, "")
    await t.run("ifup lte")
    assert (await _status(t))["up"] is True


async def test_a_healthy_session_has_the_ap2_handle(ctx: AppContext) -> None:
    t = await _transport(ctx)
    assert (await t.run("ifup lte")).ok
    assert (await _status(t))["data"] == {"cid_4": "11", "pdh_4": "90215808"}
