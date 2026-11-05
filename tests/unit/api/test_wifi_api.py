from __future__ import annotations

from typing import Any

import httpx

MAC = "f4:12:fa:f3:57:68"
N20_CH6: dict[str, Any] = {
    "radio": "radio0",
    "modes": {"kind": "set", "modes": ["n20"]},
    "channels": {"kind": "set", "channels": [6]},
}


async def test_get_wifi_state_ap2(authed: httpx.AsyncClient) -> None:
    body = (await authed.get("/api/routers/ap2/wifi")).json()
    [radio] = body["radios"]
    assert radio["name"] == "radio0" and radio["up"] is False
    assert radio["channels"]["kind"] == "none" and radio["modes"]["kind"] == "auto"
    assert radio["writers"]["cell_density"] == "dima_night"
    assert radio["limits"]["channels"] == list(range(1, 14))
    assert radio["ssids"][0]["key_set"] is True and "key" not in radio["ssids"][0]


async def test_unknown_router_is_404(authed: httpx.AsyncClient) -> None:
    assert (await authed.get("/api/routers/nope/wifi")).status_code == 404


async def test_preview_then_apply_n20_ch6(authed: httpx.AsyncClient) -> None:
    preview = (await authed.post("/api/routers/ap2/wifi/preview", json=N20_CH6)).json()
    assert preview["lines"][:2] == ["set -e", "uci set wireless.radio0.htmode='HT20'"]
    assert "script" not in preview and "secrets" not in preview and len(preview["digest"]) == 16
    assert (await authed.post("/api/routers/ap2/wifi/apply", json=N20_CH6)).status_code == 422  # no digest
    stale = await authed.post("/api/routers/ap2/wifi/apply", json={**N20_CH6, "digest": "0" * 16})
    assert stale.status_code == 409
    assert (
        stale.json()["detail"] == "AP2 · office changed since the preview. Check the new preview, then apply."
    )
    result = (
        await authed.post("/api/routers/ap2/wifi/apply", json={**N20_CH6, "digest": preview["digest"]})
    ).json()
    assert result["applied"] is True and result["verified"] is True
    assert [c["name"] for c in result["checks"]][-1] == "beacon rate"


async def test_refusal_is_422_with_text(authed: httpx.AsyncClient) -> None:
    body = {**N20_CH6, "channels": {"kind": "set", "channels": [14]}}
    r = await authed.post("/api/routers/ap2/wifi/preview", json=body)
    assert r.status_code == 422 and r.json()["detail"] == "Channel 14 is not allowed in country IL"
    r = await authed.post("/api/routers/ap2/wifi/preview", json={"radio": "radio0", "modes": {"kind": "set"}})
    assert r.status_code == 422 and r.json()["detail"] == "Tick at least one mode, or choose Auto or All."


async def test_apply_423_when_guard_live(authed_guard_live: httpx.AsyncClient) -> None:
    preview = (await authed_guard_live.post("/api/routers/ap2/wifi/preview", json=N20_CH6)).json()
    r = await authed_guard_live.post(
        "/api/routers/ap2/wifi/apply", json={**N20_CH6, "digest": preview["digest"]}
    )
    assert r.status_code == 423 and "dima_night" in r.json()["detail"]


async def test_key_not_echoed(authed: httpx.AsyncClient) -> None:
    body = {"radio": "radio0", "ssids": [{"section": "default_radio0", "key": "secret-lab-key"}]}
    preview = await authed.post("/api/routers/ap1/wifi/preview", json=body)
    assert preview.status_code == 200 and "secret-lab-key" not in preview.text
    applied = await authed.post(
        "/api/routers/ap1/wifi/apply", json={**body, "digest": preview.json()["digest"]}
    )
    assert applied.status_code == 200 and "secret-lab-key" not in applied.text


async def test_stations_and_block(authed: httpx.AsyncClient) -> None:
    [station] = (await authed.get("/api/routers/ap1/wifi/stations")).json()
    assert station["mac"] == MAC and station["name"] == "panel"
    r = await authed.post(f"/api/routers/ap1/wifi/stations/{MAC}/block", json={"seconds": 60})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await authed.get("/api/routers/ap1/wifi/stations")).json() == []
    r = await authed.post(f"/api/routers/ap1/wifi/stations/{MAC}/block", json={"seconds": 5})
    assert r.status_code == 422


async def test_deauth(authed: httpx.AsyncClient) -> None:
    assert (await authed.post(f"/api/routers/ap1/wifi/stations/{MAC}/deauth")).json() == {"ok": True}


async def test_options_list_and_apply(authed: httpx.AsyncClient) -> None:
    rows = (await authed.get("/api/routers/ap2/wifi/options", params={"radio": "radio0"})).json()
    assert len(rows) == 155 + 289
    body = {"radio": "radio0", "edits": [{"section": "radio0", "name": "beacon_int", "value": "200"}]}
    preview = (await authed.post("/api/routers/ap1/wifi/options/preview", json=body)).json()
    assert preview["lines"][1] == "uci set wireless.radio0.beacon_int='200'"
    stale = await authed.post("/api/routers/ap1/wifi/options/apply", json={**body, "digest": "0" * 16})
    assert stale.status_code == 409
    result = (
        await authed.post("/api/routers/ap1/wifi/options/apply", json={**body, "digest": preview["digest"]})
    ).json()
    assert result["verified"] is True
