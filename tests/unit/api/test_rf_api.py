"""RF live's channel analysis and frame analysis over the API (v0.7 plan Tasks 8 and 9)."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.rf.air import SCAN_DEL, scan_add, scan_command
from openwrtgui.simair import BUSY, SimAir
from openwrtgui.transport.base import CommandResult
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest

AP2 = "/api/routers/ap2/rf/radio0"
AP1 = "/api/routers/ap1/rf/radio0"


def _audit(ctx: AppContext) -> list[tuple[str, str, str]]:
    return [(e.command, e.screen, e.source) for e in reversed(ctx.audit.query())]


async def _scan(authed: httpx.AsyncClient, base: str) -> httpx.Response:
    preview = (await authed.post(f"{base}/scan/preview")).json()
    return await authed.post(f"{base}/scan", json={"digest": preview["digest"]})


async def test_parked_scan_uses_a_temporary_interface(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    preview = (await authed.post(f"{AP2}/scan/preview")).json()
    assert preview["via"] == "temporary" and preview["warnings"] == []
    assert preview["lines"] == [scan_add("phy0"), scan_command("owgscan0", on_ap=False), SCAN_DEL]
    r = await authed.post(f"{AP2}/scan", json={"digest": preview["digest"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["via"] == "temporary" and len(body["networks"]) == 6
    assert [c["channel"] for c in body["channels"]] == list(range(1, 14))
    assert all(c["busy_pct"] is not None for c in body["channels"])
    signals = [n["signal_dbm"] for n in body["networks"]]
    assert signals == sorted(signals, reverse=True)  # strongest first
    writes = [line for line in _audit(ctx) if "owgscan0" in line[0]]
    assert [c for c, _, _ in writes] == preview["lines"]
    assert {screen for _, screen, _ in writes} == {"RF live"}
    assert (await authed.get(f"{AP2}/scan")).json()["at"] == body["at"]  # kept as the last result


async def test_ap_scan_uses_ap_force_and_warns(authed: httpx.AsyncClient) -> None:
    preview = (await authed.post(f"{AP1}/scan/preview")).json()
    assert preview["via"] == "ap" and preview["lines"] == [scan_command("phy0-ap0", on_ap=True)]
    assert preview["warnings"] and "may miss up to about 2 s of traffic" in preview["warnings"][0]
    body = (await authed.post(f"{AP1}/scan", json={"digest": preview["digest"]})).json()
    assert len(body["networks"]) == 7 and [n["own"] for n in body["networks"]].count(True) == 1


async def test_scan_refused_during_a_run(
    authed_guard_live: httpx.AsyncClient, ctx_guard_live: AppContext
) -> None:
    preview = (await authed_guard_live.post(f"{AP2}/scan/preview")).json()
    r = await authed_guard_live.post(f"{AP2}/scan", json={"digest": preview["digest"]})
    assert r.status_code == 423
    assert not any("owgscan0" in c for c, _, _ in _audit(ctx_guard_live))


async def test_scan_refused_during_a_step_through(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.scans.busy = lambda router_id: "A step-through runs on AP2 · test radio0"
    r = await _scan(authed, AP2)
    assert r.status_code == 409 and r.json()["detail"].startswith("A step-through runs")
    assert not any("owgscan0" in c for c, _, _ in _audit(ctx))


async def test_refused_scan_cleans_up(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(self: SimAir, ifname: str, *, ap_force: bool) -> CommandResult:
        return CommandResult("", "", BUSY, 240)

    monkeypatch.setattr(SimAir, "_scan", refused)
    r = await _scan(authed, AP2)
    assert r.status_code == 422 and "refused the scan" in r.json()["detail"]
    assert "Device or resource busy" in r.json()["detail"]
    assert _audit(ctx)[-1][0] == SCAN_DEL  # the temporary interface is gone again


async def test_preview_changed(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    preview = (await authed.post(f"{AP2}/scan/preview")).json()
    on_air = RadioRequest(radio="radio0", modes=ModeSelection.of("n20"), channels=ChannelSelection.of(6))
    assert (await ctx.wifi.apply("ap2", on_air)).applied  # now the scan would go through the AP
    r = await authed.post(f"{AP2}/scan", json={"digest": preview["digest"]})
    assert r.status_code == 409


async def test_rf_scan_routes(authed: httpx.AsyncClient) -> None:
    assert (await authed.get(f"{AP2}/scan")).json() is None
    assert (await authed.get("/api/routers/nope/rf/radio0/scan")).status_code == 404
    assert (await authed.post(f"{AP2}/scan", json={})).status_code == 422  # no digest


async def test_bad_radio_name_422(authed: httpx.AsyncClient) -> None:
    for radio in ("radio9", "radio0;reboot", "x" * 16):
        r = await authed.post(f"/api/routers/ap2/rf/{radio}/scan/preview")
        assert r.status_code == 422, (radio, r.text)
