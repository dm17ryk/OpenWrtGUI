"""The LTE state of a simulated router and GET /lte."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from openwrtgui.context import AppContext
from openwrtgui.lte.state import read_lte
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


async def _sim(ctx: AppContext, router_id: str = "ap2") -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get(router_id))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport)
    return t


async def test_state_of_sim_ap2(ctx: AppContext) -> None:
    s = await ctx.lte.state("ap2")
    assert s.available and s.device == "/dev/cdc-wdm0" and s.note is None
    assert (s.registration, s.radio, s.roaming) == ("registered", "lte", False)
    assert (s.operator, s.operator_source, s.mcc, s.mnc) == ("Partner", "at", 425, 1)
    assert s.rsrp is not None and -98 <= s.rsrp.value <= -92 and s.rsrp.label in ("good", "fair")
    assert s.snr is not None and s.snr.label is not None
    assert (s.up, s.uptime_s, s.ipv4) == (True, 1000, "10.64.12.7")
    assert (s.rx_bytes, s.tx_bytes) == (1_204_331, 3_876_002)
    assert (s.modem.manufacturer, s.modem.model, s.modem.at_port) == ("BroadMobi", "BM806C", "/dev/ttyUSB2")
    assert s.modem.mode_order == 17 and s.opmode == "online" and s.missing == ()
    assert "qmi.sh" in s.autoconnect_note


async def test_state_without_a_modem(ctx: AppContext) -> None:
    t = await _sim(ctx)
    assert t.state is not None and t.state.modem is not None
    t.state.modem.plugged = False
    s = await ctx.lte.state("ap2")
    assert {"signal", "serving system", "operating mode", "AT"} <= set(s.missing)
    assert s.up is True and s.rsrp is None and s.operator is None


async def test_the_operator_falls_back_to_qmi_without_at(ctx: AppContext) -> None:
    t = await _sim(ctx)
    assert t.state is not None and t.state.modem is not None
    real = t.state.modem.answer

    def no_at(command: str) -> CommandResult | None:
        return CommandResult(command, "", "", 0) if "microcom" in command else real(command)

    t.state.modem.answer = no_at  # type: ignore[method-assign]
    s = await ctx.lte.state("ap2")
    assert (s.operator, s.operator_source, s.modem.at_port) == ("Partner", "qmi", None)
    assert "AT" in s.missing


class Nothing:
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        raise AssertionError(f"nothing should be read: {command}")


async def test_a_router_without_a_qmi_interface() -> None:
    s = await read_lte(Nothing(), router_id="x", qmi=None, at_port=None, now=NOW)  # type: ignore[arg-type]
    assert not s.available
    assert s.note == "This router has no LTE interface (no qmi interface in its network config)"


async def test_lte_endpoint(authed: httpx.AsyncClient) -> None:
    r = await authed.get("/api/routers/ap2/lte")
    assert r.status_code == 200
    body = r.json()
    assert body["operator"] == "Partner" and body["modem"]["model"] == "BM806C"
    assert (await authed.get("/api/routers/nope/lte")).status_code == 404
