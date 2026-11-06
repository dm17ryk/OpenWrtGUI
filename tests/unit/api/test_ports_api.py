from __future__ import annotations

import httpx

PORTS = "/api/routers/ap2/ports"


async def test_ports_state_and_enable(authed: httpx.AsyncClient) -> None:
    state = (await authed.get(PORTS)).json()
    assert state["managed"] and [p["label"] for p in state["ports"]][0] == "LAN1"
    assert state["ports"][0]["own"] is True
    body = {"port": 2, "on": False}
    preview = (await authed.post(f"{PORTS}/enable/preview", json=body)).json()
    assert preview["lines"] == ["swconfig dev switch0 port 2 set enable 0"]
    result = (await authed.post(f"{PORTS}/enable/apply", json={**body, "digest": preview["digest"]})).json()
    assert result["verified"]
    every = {"all_on": True}
    preview = (await authed.post(f"{PORTS}/enable/preview", json=every)).json()
    result = (await authed.post(f"{PORTS}/enable/apply", json={**every, "digest": preview["digest"]})).json()
    assert result["verified"]


async def test_own_port_refused(authed: httpx.AsyncClient) -> None:
    r = await authed.post(f"{PORTS}/enable/preview", json={"port": 3, "on": False})
    assert r.status_code == 422 and "carries this app's SSH" in r.json()["detail"]


async def test_vlans_and_mirror_preview(authed: httpx.AsyncClient) -> None:
    vlans = {"upserts": [{"section": None, "vlan": 3, "members": {"1": "t", "6": "t"}}], "deletes": []}
    preview = (await authed.post(f"{PORTS}/vlans/preview", json=vlans)).json()
    assert preview["rollback"] is True and any(line.endswith("ports='1t 6t'") for line in preview["lines"])
    mirror = {"monitor": 1, "sources": [{"port": 2, "rx": True, "tx": False}]}
    preview = (await authed.post(f"{PORTS}/mirror/preview", json=mirror)).json()
    assert any(line.endswith("mirror_monitor_port='1'") for line in preview["lines"])
