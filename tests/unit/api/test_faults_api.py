"""The Faults and capture endpoints, and the known devices in Settings, against the simulator."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.simulator import SIM_GUARD_ENV

FAULTS = "/api/routers/ap1/faults"
CAPTURES = "/api/routers/ap1/captures"
PANEL = {"mac": None, "ip": "192.168.1.30"}


async def _arm(authed: httpx.AsyncClient, body: dict[str, object]) -> dict[str, object]:
    preview = (await authed.post(f"{FAULTS}/preview", json=body)).json()
    return dict((await authed.post(f"{FAULTS}/apply", json={**body, "digest": preview["digest"]})).json())


async def test_fault_arm_and_clear(authed: httpx.AsyncClient) -> None:
    state = (await authed.get(FAULTS)).json()
    assert state["caps"]["family"] == "netdev" and state["armed"] == []
    result = await _arm(authed, {"kind": "block", "target": PANEL, "flow": "all_in", "loss": 100})
    assert result["verified"], result
    (armed,) = (await authed.get(FAULTS)).json()["armed"]
    assert armed["kind"] == "block" and armed["until"] is None
    preview = (await authed.post(f"{FAULTS}/clear/preview", json={"ids": None})).json()
    result = (
        await authed.post(f"{FAULTS}/clear/apply", json={"ids": None, "digest": preview["digest"]})
    ).json()
    assert result["verified"], result
    assert (await authed.get(FAULTS)).json()["armed"] == []


async def test_refusal_422(authed: httpx.AsyncClient) -> None:
    r = await authed.post(
        f"{FAULTS}/preview", json={"kind": "isolate", "target": {"mac": None, "ip": "192.168.1.10"}}
    )
    assert (
        r.status_code == 422
        and r.json()["detail"] == "192.168.1.10 is this PC (the app's connection to AP1 · bench)"
    )


async def test_clear_200_while_guard_live(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _arm(authed, {"kind": "isolate", "target": PANEL}))["verified"]
    monkeypatch.setenv(SIM_GUARD_ENV, "live")
    ctx.guard.check_local()
    preview = (await authed.post(f"{FAULTS}/clear/preview", json={"ids": None})).json()
    r = await authed.post(f"{FAULTS}/clear/apply", json={"ids": None, "digest": preview["digest"]})
    assert r.status_code == 200 and r.json()["error"].startswith("Cleared although Bench Guard is live")


async def test_capture_start_list_stop(authed: httpx.AsyncClient) -> None:
    devices = (await authed.get(f"{CAPTURES}/devices")).json()
    assert "br-lan" in devices["devices"] and "mon0" in devices["devices"] and devices["wireshark"] is False
    view = (await authed.post(CAPTURES, json={"device": "br-lan", "filter": "udp", "duration_s": 3})).json()
    stopped = (await authed.post(f"{CAPTURES}/{view['id']}/stop")).json()
    assert stopped["running"] is False
    for _ in range(50):
        listed = (await authed.get(CAPTURES)).json()
        if listed and not listed[0]["running"]:
            break
        await asyncio.sleep(0.01)
    assert listed[0]["id"] == view["id"] and listed[0]["path"].endswith(".pcap")


async def test_settings_known_devices_round_trip(authed: httpx.AsyncClient) -> None:
    settings = (await authed.get("/api/settings")).json()
    assert [t["owner"] for t in settings["known_tables"]] == ["dima_night", "voip_chain"]
    settings["known_devices"] = [{"name": "panel", "macs": ["f4:12:fa:f3:57:68", "e4:5f:01:aa:bb:01"]}]
    assert (await authed.put("/api/settings", json=settings)).status_code == 200
    assert (await authed.get("/api/settings")).json()["known_devices"][0]["name"] == "panel"
