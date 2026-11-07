"""The Firewall endpoints against the simulator."""

from __future__ import annotations

import httpx

FW = "/api/routers/{}/firewall"


async def test_firewall_state_ap1(authed: httpx.AsyncClient) -> None:
    state = (await authed.get(FW.format("ap1"))).json()
    assert state["available"] and state["own_zone"] == "lan"
    assert {o["key"]: o["owner"] for o in state["objects"]}["bridge voipdscp"] == "known"
    assert [p["id"] for p in state["pins"]] == ["ssh", "dhcpdns"]
    assert any(r["conf"]["name"] == "Allow-Ping" and r["effect"] == "allows" for r in state["rules"])
    assert state["custom"][0]["from_image"] is True


async def test_ruleset_text(authed: httpx.AsyncClient) -> None:
    text = (await authed.get(f"{FW.format('ap1')}/ruleset")).json()["text"]
    assert "table inet fw4 {" in text and "table bridge voipdscp {" in text


async def test_model_preview_then_apply_with_pin(authed: httpx.AsyncClient) -> None:
    body = {"cells": {"lan.input": "REJECT"}, "pins_removed": []}
    preview = (await authed.post(f"{FW.format('ap2')}/model/preview", json=body)).json()
    assert preview["rollback"] and any("owg_pin_ssh" in line for line in preview["lines"])
    result = (
        await authed.post(f"{FW.format('ap2')}/model/apply", json={**body, "digest": preview["digest"]})
    ).json()
    assert result["applied"] and result["verified"], result


async def test_rules_and_zones_preview(authed: httpx.AsyncClient) -> None:
    rule = {
        "name": "Block-panel-ping",
        "src": "lan",
        "proto": "icmp",
        "src_ip": ["192.168.1.20"],
        "target": "DROP",
    }
    preview = (await authed.post(f"{FW.format('ap2')}/rules/preview", json={"upserts": [rule]})).json()
    assert any(line.endswith("add firewall rule)") for line in preview["lines"])
    zone = {"name": "guest", "networks": [], "input": "REJECT", "output": "ACCEPT", "forward": "REJECT"}
    preview = (await authed.post(f"{FW.format('ap2')}/zones/preview", json={"upserts": [zone]})).json()
    assert any(line.endswith("add firewall zone)") for line in preview["lines"])
    fwd = {"name": "web", "src_dport": "8080", "dest_ip": "192.168.1.20", "dest_port": "80"}
    assert (
        await authed.post(f"{FW.format('ap2')}/forwards/preview", json={"upserts": [fwd]})
    ).status_code == 200
    custom = {"name": "20-owg", "content": "# nothing yet"}
    assert (await authed.post(f"{FW.format('ap2')}/custom/preview", json=custom)).status_code == 200


async def test_locked_table_422_without_override(authed: httpx.AsyncClient) -> None:
    body = {
        "key": "bridge voipdscp",
        "action": "edit",
        "rules": [{"chain": "post", "body": "udp dport 5004 counter"}],
    }
    r = await authed.post(f"{FW.format('ap1')}/tables/preview", json=body)
    assert (
        r.status_code == 422
        and r.json()["detail"] == "bridge voipdscp belongs to voip_chain; unlock it first."
    )
    r = await authed.post(f"{FW.format('ap1')}/tables/preview", json={**body, "override": True})
    assert r.status_code == 200 and any("nft -c -f /dev/stdin" in line for line in r.json()["lines"])


async def test_stale_digest_409(authed: httpx.AsyncClient) -> None:
    body = {"cells": {"wan.input": "DROP"}, "digest": "0000000000000000"}
    assert (await authed.post(f"{FW.format('ap2')}/model/apply", json=body)).status_code == 409


async def test_apply_423_when_guard_live(authed_guard_live: httpx.AsyncClient) -> None:
    body = {"cells": {"wan.input": "DROP"}, "digest": "0000000000000000"}
    assert (await authed_guard_live.post(f"{FW.format('ap2')}/model/apply", json=body)).status_code == 423
