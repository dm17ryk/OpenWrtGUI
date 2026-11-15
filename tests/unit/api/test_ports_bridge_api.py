"""The VLAN editor's API on ap5 (v1.0a3 D6): state, preview, refusals as 422, Bench Guard as 423 (D8)."""

from __future__ import annotations

from datetime import datetime

import httpx

from openwrtgui.context import AppContext
from openwrtgui.store.routers import RouterRecord

BASE = "/api/routers/ap5/ports/bridge"


def add_ap5(c: AppContext) -> None:
    c.routers.upsert(
        RouterRecord(
            id="ap5",
            name="AP5 · DSA image",
            host="192.168.1.7",
            auth="key",
            added_at=datetime(2026, 11, 15, 9, 0),
        )
    )


async def test_state_and_preview(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    add_ap5(ctx)
    state = (await authed.get(BASE)).json()
    assert state["bridge"] == "switch" and [v["vlan"] for v in state["vlans"]] == [1, 10]
    body = {"upserts": [{"vlan": 20, "members": {"lan2": "t"}, "local": True}], "deletes": []}
    plan = (await authed.post(f"{BASE}/preview", json=body)).json()
    assert plan["rollback"] is True
    assert any(line.endswith("add_list network.$b1.ports='lan2:t'") for line in plan["lines"])


async def test_refusals_are_422(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    add_ap5(ctx)
    body = {"upserts": [{"vlan": 20, "members": {"lan9": "t"}}], "deletes": []}
    r = await authed.post(f"{BASE}/preview", json=body)
    assert r.status_code == 422 and "lan9 is not a port of switch" in r.json()["detail"]
    assert (await authed.get("/api/routers/nope/ports/bridge")).status_code == 404


async def test_ap2_has_no_bridge(authed: httpx.AsyncClient) -> None:
    state = (await authed.get("/api/routers/ap2/ports/bridge")).json()
    assert state["bridge"] is None and state["vlans"] == []


async def test_apply_is_refused_during_a_run(
    ctx_guard_live: AppContext, authed_guard_live: httpx.AsyncClient
) -> None:
    add_ap5(ctx_guard_live)
    body = {"upserts": [{"vlan": 20, "members": {"lan2": "t"}}], "deletes": [], "digest": "0" * 16}
    r = await authed_guard_live.post(f"{BASE}/apply", json=body)
    assert r.status_code == 423
