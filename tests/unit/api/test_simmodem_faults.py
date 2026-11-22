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
UQMI_RUNNING = "ps w | grep -c '[u]qmi '"


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


async def test_autoconnect_already_off_answers_no_effect(ctx: AppContext) -> None:
    """AP2's BM806C, 2026-11-19 window: its qmi.sh turns autoconnect off at every connect, so the modem
    answers a `--set-autoconnect disabled` with QMI's "No effect" and exit 1."""
    t = await _transport(ctx)
    assert t.state.modem.autoconnect_on is False  # type: ignore[union-attr]
    answer = await t.run(AUTOCONNECT_OFF)
    assert (answer.exit_status, answer.stdout, answer.stderr) == (1, '"No effect"\n', "")


async def test_ifdown_returns_before_the_teardown_ends(ctx: AppContext) -> None:
    """AP2, 2026-11-19 window: netifd's `ifdown lte` returns while qmi.sh's teardown still runs uqmi."""
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.teardown_reads = 2
    assert (await t.run("ifdown lte")).ok
    reads = [(await t.run(UQMI_RUNNING)).stdout for _ in range(3)]
    assert reads == ["1\n", "1\n", "0\n"]


async def test_a_sync_during_the_teardown_leaves_the_session_down(ctx: AppContext) -> None:
    """AP2, 2026-11-19 window: a `--sync` sent while the teardown ran took the modem's QMI service down, and
    nothing short of a router reboot brought LTE back (a modem restart did not)."""
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.teardown_reads = 2
    await t.run("ifdown lte")
    await t.run(SYNC)
    assert modem.sync_raced is True
    for line in (LOW, ONLINE, "ifup lte"):
        await t.run(line)
    assert (await _status(t))["up"] is False


SETUP_RUNNING = "ps w | grep -c -e '[q]mi\\.sh' -e '[u]qmi '"


async def _reads(t: ReplayTransport, n: int) -> list[str]:
    return [(await t.run(SETUP_RUNNING)).stdout for _ in range(n)]


async def test_a_setup_runs_for_its_reads_after_ifup(ctx: AppContext) -> None:
    """#93: after `ifup lte`, netifd's qmi.sh setup runs uqmi for a while."""
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.setup_reads = 2
    assert (await t.run("ifup lte")).ok
    assert await _reads(t, 3) == ["1\n", "1\n", "0\n"]
    assert (await t.run(SETUP_RUNNING)).exit_status == 1  # grep -c exits 1 on none


async def test_a_failing_link_retries_after_its_gap(ctx: AppContext) -> None:
    """#93: on a link that cannot connect, netifd retries the setup after a short gap."""
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.setup_reads, modem.retry_gap, modem.stale_qmi = 2, 1, True
    modem.start_setup()
    assert await _reads(t, 6) == ["1\n", "1\n", "0\n", "1\n", "1\n", "0\n"]


async def test_with_no_gap_a_failing_setup_never_pauses(ctx: AppContext) -> None:
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.setup_reads, modem.retry_gap, modem.stale_qmi = 2, 0, True
    modem.start_setup()
    assert await _reads(t, 10) == ["1\n"] * 10


async def test_an_ifdown_mid_setup_wedges_until_a_reboot(ctx: AppContext) -> None:
    """#93, AP2 2026-11-19: an `ifdown lte` that cut qmi.sh off mid-setup left the modem's QMI channel failing
    ("Unable to obtain client ID") until a router reboot; a modem restart did not help."""
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.setup_reads = 3
    modem.start_setup()
    await t.run("ifdown lte")
    assert modem.setup_cut is True
    for line in (LOW, ONLINE, "ifup lte"):
        await t.run(line)
    assert modem.setup_cut is True
    assert (await _status(t))["up"] is False


async def test_an_ifdown_in_the_gap_is_harmless(ctx: AppContext) -> None:
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.setup_reads, modem.retry_gap = 1, 2
    modem.start_setup()
    assert await _reads(t, 1) == ["1\n"]  # the setup's one read; the gap follows
    await t.run("ifdown lte")
    assert modem.setup_cut is False


async def test_netifd_reports_pending_while_a_setup_runs(ctx: AppContext) -> None:
    t = await _transport(ctx)
    modem = t.state.modem  # type: ignore[union-attr]
    modem.connected, modem.setup_reads = False, 1
    modem.start_setup()
    assert (await _status(t))["pending"] is True
    await _reads(t, 1)
    assert (await _status(t))["pending"] is False


async def test_a_healthy_session_has_the_ap2_handle(ctx: AppContext) -> None:
    t = await _transport(ctx)
    assert (await t.run("ifup lte")).ok
    assert (await _status(t))["data"] == {"cid_4": "11", "pdh_4": "90215808"}
