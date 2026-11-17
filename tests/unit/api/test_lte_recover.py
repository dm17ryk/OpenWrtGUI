"""Recover (spec 4.2, 4.9): diagnose, then the five rungs, stopping as soon as LTE works; on the simulator."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from openwrtgui.busy import RouterBusy
from openwrtgui.context import AppContext
from openwrtgui.lte.recover import RUNGS, LteRecoverBusy, LteRecoverJob
from openwrtgui.lte.service import HARNESS_STOPPED, PUT_BACK_SCREEN
from openwrtgui.lte.settings import LteSettings
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport

DEV = "/dev/cdc-wdm0"
LOW = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode low_power"
ONLINE = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode online"
SYNC = f"uqmi -s -d {DEV} -t 5000 --sync"
AUTOCONNECT_OFF = f"uqmi -s -d {DEV} -t 5000 --set-autoconnect disabled"
NOT_RECOVERED = (
    "LTE did not come back. Reboot the router (System › Reboot), then power-cycle it if that does not help."
)
NEVER = (
    "mode reset",
    "--reset-wds",
    "--set-autoconnect enabled",
    "--set-autoconnect paused",
    "AT&F",
    "AT&W",
    "AT+CFUN",
)


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext) -> Iterator[None]:
    ctx.lte.poll_s = 0.0
    ctx.lte.readback_s = 0.0
    ctx.lte_recover.autoconnect_gap_s = 0.0
    yield
    sent = [e.command for e in ctx.audit.query()]
    assert not [c for c in sent if any(bad in c for bad in NEVER)]  # never, in any test here


async def _modem(ctx: AppContext):  # type: ignore[no-untyped-def]
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


def _calls(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def _recover(ctx: AppContext) -> LteRecoverJob:
    preview = await ctx.lte_recover.preview("ap2")
    await ctx.lte_recover.start("ap2", preview.digest)
    job = await ctx.lte_recover.finished("ap2")
    assert job is not None
    return job


def _outcomes(job: LteRecoverJob) -> list[str | None]:
    return [r.outcome for r in job.rungs]


async def _save(ctx: AppContext) -> None:
    await ctx.lte.save_setup("ap2", ctx.lte_setups)


async def _drift(ctx: AppContext) -> None:
    drift = LteSettings(apn="other")
    plan = await ctx.lte.plan_settings("ap2", drift)
    assert (await ctx.lte.apply_settings("ap2", drift, plan.digest)).applied


def _refuse(modem, line: str, times: int | None = None) -> None:  # type: ignore[no-untyped-def]
    real = modem.answer
    left = [times]

    def refusing(command: str) -> CommandResult | None:
        if command == line and (left[0] is None or left[0] > 0):
            if left[0] is not None:
                left[0] -= 1
            return CommandResult(command, "", "Request failed\n", 1)
        return real(command)

    modem.answer = refusing


async def test_the_preview_marks_the_rungs_that_run_only_if_needed(ctx: AppContext) -> None:
    preview = await ctx.lte_recover.preview("ap2")
    assert preview.lines[0] == "ifdown lte  # only if LTE does not work after the step before"
    assert f"{AUTOCONNECT_OFF}  # only if LTE does not work after the step before" in preview.lines
    assert f"{LOW}  # only if LTE does not work after the step before" in preview.lines
    assert any("No good setup is saved for AP2 · office" in w for w in preview.warnings)


async def test_a_working_modem_ends_at_once_with_nothing_written(ctx: AppContext) -> None:
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("works", "LTE works; nothing to do.")
    assert _outcomes(job) == ["not needed"] * 5
    assert _calls(ctx) == []


async def test_works_but_settings_differ_writes_nothing_and_says_so(ctx: AppContext) -> None:
    await _save(ctx)
    await _drift(ctx)
    before = len(_calls(ctx))
    job = await _recover(ctx)
    assert job.phase == "works"
    assert job.detail is not None and job.detail.startswith("LTE works; nothing to do. Its settings differ")
    assert "use Reconfigure to put them back." in job.detail
    assert len(_calls(ctx)) == before


async def test_a_dropped_session_is_back_after_reconnect(ctx: AppContext) -> None:
    (await _modem(ctx)).connected = False
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Reconnect.")
    assert "no session" in job.diagnosis
    assert _outcomes(job) == ["skipped", "works", "not needed", "not needed", "not needed"]


async def test_stale_qmi_needs_the_sync_rung(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected, modem.stale_qmi = False, True
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Clear QMI state.")
    calls = _calls(ctx)
    at = calls.index(SYNC)
    assert calls[at - 1 : at + 2] == ["ifdown lte", SYNC, "ifup lte"]


async def test_modem_autoconnect_needs_the_autoconnect_rung(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected, modem.autoconnect_on, modem.autoconnect_refusals = False, True, 2
    job = await _recover(ctx)
    assert (job.phase, job.detail) == (
        "recovered",
        "LTE works again after: Turn off the modem's autoconnect.",
    )
    calls = _calls(ctx)
    first = calls.index(AUTOCONNECT_OFF)
    assert calls[first - 1 : first + 4] == ["ifdown lte", *[AUTOCONNECT_OFF] * 3, "ifup lte"]


async def test_autoconnect_that_never_takes_goes_on_to_the_restart(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected, modem.autoconnect_on, modem.autoconnect_refusals = False, True, 10
    job = await _recover(ctx)
    rung = job.rungs[3]
    assert rung.outcome == "failed" and rung.detail is not None and AUTOCONNECT_OFF in rung.detail
    assert _calls(ctx).count(AUTOCONNECT_OFF) == 10
    assert job.rungs[4].outcome is not None and LOW in _calls(ctx)


async def test_a_wedged_modem_needs_the_restart_rung(ctx: AppContext) -> None:
    (await _modem(ctx)).wedged = True
    job = await _recover(ctx)
    assert "session up but no packet-data handle" in job.diagnosis
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Restart the modem.")
    assert _outcomes(job)[1:4] == ["not yet", "not yet", "not yet"]


async def test_a_failing_sync_goes_on_to_the_next_rung(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected, modem.stale_qmi = False, True
    _refuse(modem, SYNC, times=1)
    job = await _recover(ctx)
    assert job.rungs[2].outcome == "failed" and SYNC in (job.rungs[2].detail or "")
    assert job.rungs[3].outcome is not None and AUTOCONNECT_OFF in _calls(ctx)
    assert "ifup lte" in _calls(ctx)[_calls(ctx).index(SYNC) :]


async def test_differing_settings_are_put_back_first(ctx: AppContext) -> None:
    await _save(ctx)
    await _drift(ctx)
    (await _modem(ctx)).connected = False
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Put back the saved setup.")
    assert any("settings differ from the good setup saved" in d and "apn" in d for d in job.diagnosis)
    _rows, values = await ctx.net.interface_values("ap2", "lte")
    assert values["apn"] == "uinternet"


async def test_nothing_helps_ends_not_recovered_with_the_reboot_advice(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected, modem.stale_qmi = False, True
    _refuse(modem, SYNC)
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("not recovered", NOT_RECOVERED)
    assert job.rungs[4].outcome == "not yet"
    assert modem.opmode == "online"


async def test_stop_finishes_the_put_back(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.wedged = True
    real = modem.answer

    def stopping(command: str) -> CommandResult | None:
        if command == LOW:
            ctx.lte_recover.request_stop("ap2")  # Stop pressed while the modem goes to low power
        return real(command)

    modem.answer = stopping
    job = await _recover(ctx)
    assert job.phase == "stopped"
    assert job.detail in ("Stopped; LTE works.", "Stopped; LTE does not work.")
    assert modem.opmode == "online" and modem.connected
    calls = _calls(ctx)
    assert calls.index(ONLINE) > calls.index(LOW) and calls[-1] == "ifup lte"


async def test_a_harness_run_mid_rung_puts_back_and_stops(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    modem = await _modem(ctx)
    modem.wedged = True
    real = modem.answer

    def run_starts(command: str) -> CommandResult | None:
        result = real(command)
        if command == LOW:
            monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
            ctx.guard.check_local()
        return result

    modem.answer = run_starts
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("stopped", HARNESS_STOPPED)
    put_back = [e.command for e in reversed(ctx.audit.query()) if e.screen == PUT_BACK_SCREEN]
    assert put_back == [ONLINE, "ifup lte"]
    assert modem.opmode == "online" and modem.connected


async def _held(ctx: AppContext) -> asyncio.Event:
    """A Recover that waits in its Reconnect check until the returned event is set."""
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    ctx.lte._sleep = slow  # type: ignore[assignment]
    ctx.lte.poll_s = 1.0
    (await _modem(ctx)).wedged = True
    preview = await ctx.lte_recover.preview("ap2")
    await ctx.lte_recover.start("ap2", preview.digest)
    for _ in range(100):
        await asyncio.sleep(0.01)
        job = ctx.lte_recover.job("ap2")
        if job is not None and job.current == 1:
            break
    return gate


async def test_two_starts_one_job(ctx: AppContext) -> None:
    (await _modem(ctx)).connected = False
    preview = await ctx.lte_recover.preview("ap2")
    results = await asyncio.gather(
        ctx.lte_recover.start("ap2", preview.digest),
        ctx.lte_recover.start("ap2", preview.digest),
        return_exceptions=True,
    )
    assert sum(isinstance(r, LteRecoverJob) for r in results) == 1
    (refused,) = [r for r in results if isinstance(r, Exception)]
    assert isinstance(refused, LteRecoverBusy) and "AP2 · office" in str(refused)
    await ctx.lte_recover.finished("ap2")


async def test_an_update_asks_and_stops_the_job(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    gate = await _held(ctx)
    asked = await authed.post("/api/update/install", json={"version": "9.9.9"})
    assert asked.status_code == 409 and "LTE recovery on AP2 · office" in asked.json()["live"]
    gate.set()
    await ctx.lte_recover.stop_all(limit_s=5)
    job = ctx.lte_recover.job("ap2")
    assert job is not None and job.phase == "stopped"
    assert ctx.lte_recover.live() == []


async def test_an_unreachable_router_fails_the_job(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.connected = False
    real = modem.answer

    def dead(command: str) -> CommandResult | None:
        if command == "ifdown lte":
            raise TransportError("connection lost")
        return real(command)

    modem.answer = dead
    job = await _recover(ctx)
    assert job.phase == "failed"
    assert job.error is not None and "ifdown lte" in job.error and "AP2 · office did not answer" in job.error
    assert ctx.lte_recover.busy("ap2") is None


async def test_other_writes_are_refused_while_it_runs(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    gate = await _held(ctx)
    try:
        busy = "LTE recovery runs on AP2 · office"
        plan = await ctx.lte.plan_action("ap2", "connect")
        with pytest.raises(RouterBusy, match=busy):
            await ctx.lte.apply_action("ap2", "connect", plan.digest)
        settings = await authed.post(
            "/api/routers/ap2/lte/settings/apply", json={"apn": "x", "digest": "0" * 16}
        )
        assert (settings.status_code, settings.json()["detail"]) == (409, busy)
        at = await authed.post("/api/routers/ap2/lte/at", json={"command": "AT+COPS=0", "confirmed": True})
        assert (at.status_code, at.json()["detail"]) == (409, busy)
        query = await authed.post("/api/routers/ap2/lte/at", json={"command": "AT+CSQ"})
        assert query.status_code == 200  # a query still runs
    finally:
        gate.set()
        await ctx.lte_recover.finished("ap2")


async def test_a_step_through_blocks_recover_and_recover_blocks_a_step_through(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = await _held(ctx)
    try:
        assert any(check("ap2") == "LTE recovery runs on AP2 · office" for check in ctx.steps._busy)
        assert (
            ctx.system.extra_busy is not None
            and ctx.system.extra_busy("ap2") == "LTE recovery runs on AP2 · office"
        )
    finally:
        gate.set()
        await ctx.lte_recover.finished("ap2")
    monkeypatch.setattr(ctx.steps, "busy", lambda router_id: "A step-through runs on AP2 · office radio0")
    preview = await ctx.lte_recover.preview("ap2")
    with pytest.raises(LteRecoverBusy, match="A step-through runs"):
        await ctx.lte_recover.start("ap2", preview.digest)


READ = f"uqmi -s -d {DEV} -t 2000 --get-device-operating-mode"


async def test_no_answer_after_low_power_says_the_modem_is_in_low_power(ctx: AppContext) -> None:
    """Final review I1: the result names where the modem was left when the router stops answering."""
    modem = await _modem(ctx)
    modem.wedged = True
    real = modem.answer

    def dead_after_low(command: str) -> CommandResult | None:
        if command == READ and modem.opmode == "low_power":
            raise TransportError("connection lost")
        return real(command)

    modem.answer = dead_after_low
    job = await _recover(ctx)
    assert job.phase == "failed"
    assert job.error is not None and "did not answer" in job.error and "in low power" in job.error


async def test_a_put_back_without_an_answer_says_where_the_modem_is(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.wedged = True
    real = modem.answer

    def stop_then_die(command: str) -> CommandResult | None:
        if command == LOW:
            ctx.lte_recover.request_stop("ap2")
        if command == ONLINE:
            raise TransportError("connection lost")
        return real(command)

    modem.answer = stop_then_die
    job = await _recover(ctx)
    assert job.phase == "stopped"
    assert job.error is not None and ONLINE in job.error and "in low power" in job.error


async def test_a_cancelled_job_says_where_the_modem_is(ctx: AppContext) -> None:
    gate = asyncio.Event()
    modem = await _modem(ctx)

    async def stuck(_s: float) -> None:  # only the low_power read-back's wait between tries hangs
        if modem.opmode == "low_power":
            await gate.wait()

    modem.wedged = True
    real = modem.answer

    def never_low(command: str) -> CommandResult | None:  # the read-back waits between its tries
        if command == READ and modem.opmode == "low_power":
            return CommandResult(command, '"online"\n', "", 0)
        return real(command)

    modem.answer = never_low
    ctx.lte._sleep = stuck  # type: ignore[assignment]
    ctx.lte.readback_s = 1.0
    preview = await ctx.lte_recover.preview("ap2")
    await ctx.lte_recover.start("ap2", preview.digest)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if LOW in _calls(ctx):
            break
    await ctx.lte_recover.stop_all(limit_s=0.05)
    job = ctx.lte_recover.job("ap2")
    assert job is not None and job.phase != "running"
    assert job.error is not None and "in low power" in job.error
    gate.set()


async def test_an_unreadable_own_setup_does_not_block_recover(ctx: AppContext) -> None:
    """Final review I2: the preview names the file and Recover starts at Reconnect."""
    (ctx.data.lte_setups_dir / "ap2.json").write_text("{", encoding="utf-8")
    (await _modem(ctx)).connected = False
    preview = await ctx.lte_recover.preview("ap2")
    assert any("ap2.json cannot be read" in w for w in preview.warnings)
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Reconnect.")
    assert job.rungs[0].outcome == "skipped"


async def test_a_setup_that_cannot_be_put_back_goes_on_to_reconnect(ctx: AppContext) -> None:
    """Final review I3: rung 1 fails, says why, and the job goes on; the preview says it too."""
    await _save(ctx)
    setup = ctx.lte_setups.get("ap2")
    assert setup is not None
    ctx.lte_setups.save(setup.model_copy(update={"options": {**setup.options, "mtu": "abc"}}))
    (await _modem(ctx)).connected = False
    preview = await ctx.lte_recover.preview("ap2")
    assert any("not a whole number" in w for w in preview.warnings)
    job = await _recover(ctx)
    assert job.rungs[0].outcome == "failed" and "not a whole number" in (job.rungs[0].detail or "")
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Reconnect.")


async def test_remove_waits_for_the_job(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    """Final review I5: removing a router mid-job would drop its connection with the modem in low power."""
    gate = await _held(ctx)
    try:
        refused = await authed.delete("/api/routers/ap2")
        assert (refused.status_code, refused.json()["detail"]) == (409, "LTE recovery runs on AP2 · office")
        assert ctx.routers.get("ap2") is not None
    finally:
        gate.set()
        await ctx.lte_recover.finished("ap2")


async def test_a_settings_apply_holds_off_recover(ctx: AppContext) -> None:
    """PR #82 review: a Settings or Reconfigure apply holds the LTE busy reservation for its whole run."""
    gate = asyncio.Event()
    real = ctx.net.apply_interface

    async def slow_apply(*args, **kwargs):  # type: ignore[no-untyped-def]
        await gate.wait()
        return await real(*args, **kwargs)

    ctx.net.apply_interface = slow_apply  # type: ignore[method-assign]
    drift = LteSettings(apn="other")
    plan = await ctx.lte.plan_settings("ap2", drift)
    applying = asyncio.create_task(ctx.lte.apply_settings("ap2", drift, plan.digest))
    await asyncio.sleep(0.05)
    try:
        preview = await ctx.lte_recover.preview("ap2")
        with pytest.raises(LteRecoverBusy, match="An LTE action is already running on AP2 · office"):
            await ctx.lte_recover.start("ap2", preview.digest)
        with pytest.raises(RouterBusy, match="An LTE action is already running"):
            await ctx.lte.apply_settings("ap2", drift, plan.digest)
    finally:
        gate.set()
        await applying


async def test_an_at_write_rechecks_recover_after_connecting(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #82 review: Recover starting while the AT write waits for its connection gets the write a 409."""
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    ctx.lte._sleep = slow  # type: ignore[assignment]
    ctx.lte.poll_s = 1.0
    (await _modem(ctx)).wedged = True
    preview = await ctx.lte_recover.preview("ap2")
    real_get = ctx.pool.get
    started = False

    async def get(rec):  # type: ignore[no-untyped-def]
        nonlocal started
        t = await real_get(rec)
        if not started:  # the connection is ready just as Recover starts
            started = True
            await ctx.lte_recover.start("ap2", preview.digest)
        return t

    monkeypatch.setattr(ctx.pool, "get", get)
    try:
        with pytest.raises(RouterBusy, match="LTE recovery runs on AP2 · office"):
            await ctx.lte.at_command("ap2", "AT+COPS=0", confirmed=True)
        assert not any("AT+COPS=0" in c for c in _calls(ctx))
    finally:
        gate.set()
        await ctx.lte_recover.finished("ap2")


async def test_an_applied_setup_with_an_error_is_shown(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #82 review: rung 1's apply can be applied and still carry an error; the job keeps it."""
    await _save(ctx)
    await _drift(ctx)
    (await _modem(ctx)).connected = False

    async def applied_with_error(router_id: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
        ctx.guard.check_local()
        return NetApplyResult(router_id, True, False, (), "Confirmed after a harness run began", "127.0.0.1")

    monkeypatch.setattr(ctx.lte, "apply_setup", applied_with_error)
    job = await _recover(ctx)
    assert job.phase == "stopped"
    assert job.rungs[0].outcome == "failed"
    assert "Confirmed after a harness run began" in (job.rungs[0].detail or "")


async def test_two_saves_for_one_router_run_one_at_a_time(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #82 review: two Saves for one router would race on the same temporary file."""
    lock = threading.Lock()
    active = most = 0
    real = ctx.lte_setups.save

    def tracked(setup):  # type: ignore[no-untyped-def]
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        time.sleep(0.05)
        real(setup)
        with lock:
            active -= 1

    monkeypatch.setattr(ctx.lte_setups, "save", tracked)
    await asyncio.gather(ctx.lte.save_setup("ap2", ctx.lte_setups), ctx.lte.save_setup("ap2", ctx.lte_setups))
    assert most == 1


async def test_rung_1_goes_on_over_the_pools_new_connection(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #82 review: the rollback runner reconnects (pool.drop); the next checks use the pool's new one."""
    await _save(ctx)
    await _drift(ctx)
    (await _modem(ctx)).connected = False
    real = ctx.lte.apply_setup

    async def apply_then_reconnect(*args, **kwargs):  # type: ignore[no-untyped-def]
        old = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]  # the job's connection
        result = await real(*args, **kwargs)

        async def closed(*_a, **_k):  # type: ignore[no-untyped-def]
            raise TransportError("this connection was closed")

        monkeypatch.setattr(old, "run", closed)
        await ctx.pool.drop("ap2")
        return result

    monkeypatch.setattr(ctx.lte, "apply_setup", apply_then_reconnect)
    job = await _recover(ctx)
    assert (job.phase, job.detail) == ("recovered", "LTE works again after: Put back the saved setup.")


async def test_the_harness_put_back_holds_the_write_lock(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #82 review: past Bench Guard, but still serialised with the router's other writes."""
    modem = await _modem(ctx)
    modem.wedged = True
    real_answer = modem.answer

    def run_starts(command: str) -> CommandResult | None:
        result = real_answer(command)
        if command == LOW:
            monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
            ctx.guard.check_local()
        return result

    modem.answer = run_starts
    held: list[bool] = []
    real_put_back = ctx.lte._put_back

    async def tracked(rec, t, command):  # type: ignore[no-untyped-def]
        held.append(ctx.pool.write_lock("ap2").locked())
        return await real_put_back(rec, t, command)

    monkeypatch.setattr(ctx.lte, "_put_back", tracked)
    job = await _recover(ctx)
    assert job.phase == "stopped"
    assert held == [True, True]


def test_the_rungs_are_the_specs() -> None:
    assert RUNGS == (
        "Put back the saved setup",
        "Reconnect",
        "Clear QMI state",
        "Turn off the modem's autoconnect",
        "Restart the modem",
    )
