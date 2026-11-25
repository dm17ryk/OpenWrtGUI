"""The USSD card's endpoints (v1.3b E8, E9) in the simulator: a code behind a preview and its digest, a 35 s
listen on the AT port, and the session closed by the app when it cannot follow it."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.lte import commands as c
from openwrtgui.lte.service import PUT_BACK_SCREEN, SCREEN
from openwrtgui.simmodem import AT_PORT, SimModem
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport

BASE = "/api/routers/ap1/lte/ussd"
LISTENS = "The app listens up to 35 s for the network's reply; the AT console waits until then"
BUSY = "An LTE action is already running on AP1 · bench"
CANCEL = c.at(AT_PORT, c.USSD_CANCEL)


def _line(code: str) -> str:
    return c.ussd(AT_PORT, code)


async def _transport(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t


async def _modem(ctx: AppContext) -> SimModem:
    modem = (await _transport(ctx)).state.modem  # type: ignore[union-attr]
    assert modem is not None
    return modem


def _audited(ctx: AppContext) -> list[tuple[str, str]]:
    return [(e.command, e.screen) for e in reversed(ctx.audit.query())]


async def _preview(client: httpx.AsyncClient, code: str) -> httpx.Response:
    return await client.post(f"{BASE}/preview", json={"code": code})


async def _apply(client: httpx.AsyncClient, code: str) -> httpx.Response:
    digest = (await _preview(client, code)).json()["digest"]
    return await client.post(f"{BASE}/apply", json={"code": code, "digest": digest})


# ---------------------------------------------------------------- the preview
async def test_the_preview_is_the_ussd_line_with_the_listen_warning(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    answer = await _preview(authed, "*100#")
    assert answer.status_code == 200
    body = answer.json()
    assert body["lines"] == [_line("*100#")]
    assert body["warnings"] == [LISTENS]
    assert body["digest"]
    assert ctx.audit.query() == []
    assert _line("*100#") not in (await _transport(ctx)).calls


async def test_a_code_that_is_not_ussd_is_a_422_with_the_rule(authed: httpx.AsyncClient) -> None:
    bad = await _preview(authed, "100")
    assert (bad.status_code, bad.json()) == (422, {"detail": c.USSD_MESSAGE})
    assert (await _preview(authed, "*" + "1" * 39 + "#")).status_code == 422  # 41 characters


async def test_no_at_port_is_a_422_naming_the_router(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    (await _modem(ctx)).plugged = False
    answer = await _preview(authed, "*100#")
    assert (answer.status_code, answer.json()) == (422, {"detail": "No AT port answered on AP1 · bench"})


@pytest.mark.parametrize("path", ["preview", "apply"])
async def test_an_unknown_router_is_a_404(authed: httpx.AsyncClient, path: str) -> None:
    body = {"code": "*100#", "digest": "x"}
    assert (await authed.post(f"/api/routers/nope/lte/ussd/{path}", json=body)).status_code == 404


# ---------------------------------------------------------------- Apply (E8, E9)
async def test_a_reply_comes_back_and_the_app_sends_no_cancel(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    answer = await _apply(authed, "*100#")
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "reply", "text": "Balance 12.34", "dcs": 15, "closed": False},
    )
    assert _audited(ctx) == [(_line("*100#"), SCREEN)]
    assert CANCEL not in (await _transport(ctx)).calls


async def test_a_reply_asking_for_more_is_closed_by_the_app(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    answer = await _apply(authed, "*111#")
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "more", "text": "1 Balance 2 Packages", "dcs": 15, "closed": True},
    )
    assert _audited(ctx) == [(_line("*111#"), SCREEN), (CANCEL, SCREEN)]


async def test_a_ucs2_reply_is_decoded(authed: httpx.AsyncClient) -> None:
    body = (await _apply(authed, "*200#")).json()
    assert (body["status"], body["text"], body["dcs"], body["closed"]) == ("reply", "שלום", 72, False)


async def test_an_unknown_code_is_no_reply_and_the_app_closes_the_session(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    answer = await _apply(authed, "*999#")
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "no reply", "text": None, "dcs": None, "closed": True},
    )
    assert _audited(ctx) == [(_line("*999#"), SCREEN), (CANCEL, SCREEN)]


@pytest.mark.parametrize(("code", "error"), [("*400#", "ERROR"), ("*401#", "+CME ERROR: 30")])
async def test_an_at_error_to_the_code_is_an_error_and_the_app_closes_the_session(
    authed: httpx.AsyncClient, ctx: AppContext, code: str, error: str
) -> None:
    """P10: the modem refused the request at once (no network, a session already open): "error" with its line,
    not "no reply"; AT+CUSD=2 still goes, and closed follows its answer."""
    (await _modem(ctx)).ussd_errors[code] = error
    answer = await _apply(authed, code)
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "error", "text": error, "dcs": None, "closed": True},
    )
    assert _audited(ctx) == [(_line(code), SCREEN), (CANCEL, SCREEN)]


@pytest.mark.parametrize(("m", "status"), [(2, "ended"), (3, "ended"), (4, "error"), (5, "error")])
async def test_a_session_the_network_ended_or_refused_is_not_cancelled(
    authed: httpx.AsyncClient, ctx: AppContext, m: int, status: str
) -> None:
    """Review Focus 3: a clear status; the app sends AT+CUSD=2 only after m=1 or no reply (E9)."""
    (await _modem(ctx)).ussd_replies["*300#"] = (m, "Session over", 15)
    body = (await _apply(authed, "*300#")).json()
    assert (body["status"], body["text"], body["closed"]) == (status, "Session over", False)
    assert CANCEL not in (await _transport(ctx)).calls


async def test_a_reply_with_commas_and_quotes_inside_comes_back_whole(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    (await _modem(ctx)).ussd_replies["*101#"] = (0, 'Balance: 1,50; "ok"', 15)
    assert (await _apply(authed, "*101#")).json()["text"] == 'Balance: 1,50; "ok"'


async def test_a_reply_read_before_microcom_was_killed_still_counts(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """A reply that arrives after 5 s keeps microcom listening past the 35 s kill: its exit is 137, but the
    +CUSD line is in what it printed."""
    modem = await _modem(ctx)
    real = modem.answer

    def killed(command: str) -> CommandResult | None:
        result = real(command)
        if command == _line("*100#") and result is not None:
            return CommandResult(command, result.stdout, "", 137)
        return result

    modem.answer = killed  # type: ignore[method-assign]
    body = (await _apply(authed, "*100#")).json()
    assert (body["status"], body["text"], body["closed"]) == ("reply", "Balance 12.34", False)


async def test_the_ussd_line_gets_a_45_s_transport_timeout(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    t = await _transport(ctx)
    real = t.run
    timeouts: list[tuple[str, float]] = []

    async def spied(command: str, *, timeout: float = 15.0) -> CommandResult:
        timeouts.append((command, timeout))
        return await real(command, timeout=timeout)

    t.run = spied  # type: ignore[method-assign]
    await _apply(authed, "*100#")
    assert (_line("*100#"), 45.0) in timeouts
    assert c.USSD_TIMEOUT_S == 45.0


@pytest.mark.parametrize("fault", ["refused", "lost"])
async def test_a_cancel_that_fails_still_returns_the_reply_not_closed(
    authed: httpx.AsyncClient, ctx: AppContext, fault: str
) -> None:
    modem = await _modem(ctx)
    real = modem.answer

    def failing(command: str) -> CommandResult | None:
        if command == CANCEL:
            if fault == "lost":
                raise TransportError("connection lost")
            return CommandResult(command, "AT+CUSD=2\r\r\nERROR\r\n", "", 0)
        return real(command)

    modem.answer = failing  # type: ignore[method-assign]
    answer = await _apply(authed, "*111#")
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "more", "text": "1 Balance 2 Packages", "dcs": 15, "closed": False},
    )


# ---------------------------------------------------------------- refusals
async def test_a_live_guard_previews_but_refuses_apply_and_sends_nothing(
    authed_guard_live: httpx.AsyncClient, ctx_guard_live: AppContext
) -> None:
    preview = await _preview(authed_guard_live, "*100#")
    assert preview.status_code == 200
    answer = await authed_guard_live.post(
        f"{BASE}/apply", json={"code": "*100#", "digest": preview.json()["digest"]}
    )
    assert answer.status_code == 423
    assert ctx_guard_live.audit.query() == []
    assert _line("*100#") not in (await _transport(ctx_guard_live)).calls


async def test_a_digest_of_another_code_is_a_409_and_sends_nothing(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    digest = (await _preview(authed, "*100#")).json()["digest"]
    answer = await authed.post(f"{BASE}/apply", json={"code": "*111#", "digest": digest})
    assert answer.status_code == 409
    assert ctx.audit.query() == []


async def test_apply_while_another_lte_write_runs_is_a_409(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    digest = (await _preview(authed, "*100#")).json()["digest"]
    async with ctx.lte.write_slot(ctx.routers.get("ap1")):  # type: ignore[arg-type]
        answer = await authed.post(f"{BASE}/apply", json={"code": "*100#", "digest": digest})
    assert (answer.status_code, answer.json()) == (409, {"detail": BUSY})
    assert ctx.audit.query() == []


# ---------------------------------------------------------------- Review Focus 4: a run or Recover meanwhile
async def test_a_run_that_starts_during_the_wait_still_gets_the_reply_and_the_cancel(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request went out before the run: its reply comes back, and AT+CUSD=2 closes the session past Bench
    Guard, marked as a put-back line."""
    modem = await _modem(ctx)
    real = modem.answer

    def run_starts(command: str) -> CommandResult | None:
        result = real(command)
        if command == _line("*111#"):
            monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
            ctx.guard.check_local()
        return result

    modem.answer = run_starts  # type: ignore[method-assign]
    answer = await _apply(authed, "*111#")
    assert ctx.guard.state().live
    assert (answer.status_code, answer.json()) == (
        200,
        {"status": "more", "text": "1 Balance 2 Packages", "dcs": 15, "closed": True},
    )
    assert _audited(ctx) == [(_line("*111#"), SCREEN), (CANCEL, PUT_BACK_SCREEN)]


async def test_recover_started_during_the_wait_is_a_409(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    """P2: Recover's refusal is the LTE action text; the USSD's reply still comes back."""
    recover = (await authed.post("/api/routers/ap1/lte/recover/preview")).json()["digest"]
    digest = (await _preview(authed, "*100#")).json()["digest"]
    t = await _transport(ctx)
    real = t.run
    started, release = asyncio.Event(), asyncio.Event()

    async def held(command: str, *, timeout: float = 15.0) -> CommandResult:
        if command == _line("*100#"):
            started.set()
            await release.wait()
        return await real(command, timeout=timeout)

    t.run = held  # type: ignore[method-assign]
    apply = asyncio.create_task(authed.post(f"{BASE}/apply", json={"code": "*100#", "digest": digest}))
    try:
        await asyncio.wait_for(started.wait(), 5)
        refused = await authed.post("/api/routers/ap1/lte/recover", json={"digest": recover})
    finally:
        release.set()
    answer = await apply
    assert (refused.status_code, refused.json()) == (409, {"detail": BUSY})
    assert (answer.status_code, answer.json()["text"]) == (200, "Balance 12.34")
    assert ctx.lte_recover.job("ap1") is None
