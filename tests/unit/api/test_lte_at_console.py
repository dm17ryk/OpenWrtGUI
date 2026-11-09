"""The AT console (D5) and the IMEI on request (D3) in the simulator."""

from __future__ import annotations

import re

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.lte.commands import AT_MESSAGE
from openwrtgui.lte.service import AtNeedsConfirm
from openwrtgui.transport.fake import ReplayTransport

PORT = "/dev/ttyUSB2"


def _microcom(quoted: str) -> str:
    return f"printf '%s\\r' {quoted} | timeout -s KILL 10 microcom -t 2000 -s 115200 {PORT}"


def _commands(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def test_a_query_returns_the_modem_lines(ctx: AppContext) -> None:
    result = await ctx.lte.at_command("ap2", "AT+COPS?", confirmed=False)
    assert (result.command, result.status, result.error) == ("AT+COPS?", "OK", None)
    assert result.lines == ('+COPS: 0,0,"Partner",7',)
    assert _commands(ctx)[-1] == _microcom("'AT+COPS?'")


@pytest.mark.parametrize("text", ["ATI\nreboot", "rm -rf /", "AT" + "I" * 9998])
async def test_at_console_refuses_unsafe_text(ctx: AppContext, text: str) -> None:
    with pytest.raises(ValueError, match=f"^{AT_MESSAGE}$"):
        await ctx.lte.at_command("ap2", text, confirmed=True)
    assert ctx.audit.query() == []


async def test_at_text_is_one_shell_quoted_printf_argument(ctx: AppContext) -> None:
    result = await ctx.lte.at_command("ap2", 'AT+CGDCONT=1,"IP","a$(x)b"', confirmed=True)
    assert result.status == "OK"
    assert _commands(ctx)[-1] == _microcom('\'AT+CGDCONT=1,"IP","a$(x)b"\'')


@pytest.mark.parametrize(
    "text",
    [
        "AT+CPIN=1234",
        'AT+CPIN="1234"',
        'at+clck="SC",0,"1234"',
        'AT+CPWD="SC","1234","5678"',
        "AT+CPIN=12'34",
    ],
)
async def test_a_sim_pin_sent_in_the_console_is_hidden_in_the_audit(ctx: AppContext, text: str) -> None:
    result = await ctx.lte.at_command("ap2", text, confirmed=True)
    assert result.status == "OK"
    commands = _commands(ctx)
    assert "<hidden>" in commands[-1]
    assert not any(pin in command for command in commands for pin in ("1234", "5678", "34"))


async def test_at_console_during_a_run(ctx_guard_live: AppContext) -> None:
    csq = await ctx_guard_live.lte.at_command("ap2", "AT+CSQ", confirmed=False)
    assert (csq.status, csq.lines) == ("OK", ("+CSQ: 20,99",))
    with pytest.raises(GuardLocked):
        await ctx_guard_live.lte.at_command("ap2", "AT+CFUN=0", confirmed=True)
    assert _microcom("'AT+CFUN=0'") not in _commands(ctx_guard_live)


async def test_a_command_that_may_change_the_modem_needs_confirm(ctx: AppContext) -> None:
    with pytest.raises(
        AtNeedsConfirm, match="^This command may change the modem; send it again with confirm$"
    ):
        await ctx.lte.at_command("ap2", "AT+CFUN=0", confirmed=False)
    assert ctx.audit.query() == []


async def test_no_at_port_is_no_answer(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    t.state.modem.plugged = False
    result = await ctx.lte.at_command("ap2", "ATI", confirmed=False)
    assert (result.status, result.lines) == ("no answer", ())
    assert result.error == "No AT port answered on AP2 · office"


async def test_at_and_imei_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ok = await authed.post("/api/routers/ap2/lte/at", json={"command": "AT+CSQ", "confirmed": False})
    assert (ok.status_code, ok.json()["status"], ok.json()["lines"]) == (200, "OK", ["+CSQ: 20,99"])
    unconfirmed = await authed.post(
        "/api/routers/ap2/lte/at", json={"command": "AT+CFUN=1", "confirmed": False}
    )
    assert unconfirmed.status_code == 428
    assert unconfirmed.json()["detail"] == "This command may change the modem; send it again with confirm"
    bad = await authed.post("/api/routers/ap2/lte/at", json={"command": "reboot", "confirmed": True})
    assert (bad.status_code, bad.json()["detail"]) == (422, AT_MESSAGE)
    imei = await authed.post("/api/routers/ap2/lte/imei")
    assert (imei.status_code, imei.json()) == (200, {"imei": "353000000000001"})
    assert not any(re.search(r"[0-9]{15}", e.command) for e in ctx.audit.query())
