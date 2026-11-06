from __future__ import annotations

import httpx

PANEL = "f4:12:fa:f3:57:68"
NET = "/api/routers/{id}/network"


def url(router_id: str, path: str = "") -> str:
    return NET.format(id=router_id) + path


async def test_network_state_ap2(authed: httpx.AsyncClient) -> None:
    body = (await authed.get(url("ap2"))).json()
    assert body["own_interface"] == "lan" and body["router_ip"] == "192.168.1.2"
    lan = next(v for v in body["interfaces"] if v["conf"] and v["conf"]["name"] == "lan")
    assert lan["own"] and lan["conf"]["address"] == {"ip": "192.168.1.2", "prefix": 24}
    assert {p["name"]: p["label"] for p in body["protocols"]}["dhcp"] == "DHCP client"


async def test_unknown_router_is_404(authed: httpx.AsyncClient) -> None:
    assert (await authed.get(url("nope"))).status_code == 404


async def test_interface_preview_then_apply_follows_address(authed: httpx.AsyncClient) -> None:
    body = {"name": "lan", "address": "192.168.1.12/24"}
    preview = (await authed.post(url("ap2", "/interfaces/preview"), json=body)).json()
    assert preview["rollback"] is True and preview["target_host"] == "192.168.1.12"
    assert "secrets" not in preview and "ops" not in preview and len(preview["digest"]) == 16
    result = (
        await authed.post(url("ap2", "/interfaces/apply"), json={**body, "digest": preview["digest"]})
    ).json()
    assert result["applied"] and result["verified"] and result["host"] == "192.168.1.12"
    assert (await authed.get("/api/routers/ap2")).json()["record"]["host"] == "192.168.1.12"
    back = {"name": "lan", "address": "192.168.1.2/24"}
    preview = (await authed.post(url("ap2", "/interfaces/preview"), json=back)).json()
    result = (
        await authed.post(url("ap2", "/interfaces/apply"), json={**back, "digest": preview["digest"]})
    ).json()
    assert result["verified"] and result["host"] == "192.168.1.2"


async def test_refusal_is_422_with_text(authed: httpx.AsyncClient) -> None:
    r = await authed.post(url("ap2", "/interfaces/preview"), json={"name": "lan", "address": "192.168.1.12"})
    assert r.status_code == 422 and r.json()["detail"].startswith("Write the address with its prefix")


async def test_apply_423_when_guard_live(authed_guard_live: httpx.AsyncClient) -> None:
    body = {"name": "lan", "mtu": 1400}
    preview = (await authed_guard_live.post(url("ap2", "/interfaces/preview"), json=body)).json()
    r = await authed_guard_live.post(
        url("ap2", "/interfaces/apply"), json={**body, "digest": preview["digest"]}
    )
    assert r.status_code == 423 and "dima_night" in r.json()["detail"]


async def test_apply_with_stale_digest_409(authed: httpx.AsyncClient) -> None:
    r = await authed.post(
        url("ap2", "/dhcp/apply"), json={"interface": "lan", "start": 50, "digest": "0" * 16}
    )
    assert r.status_code == 409


async def test_dhcp_preview_warns_about_ap1(authed: httpx.AsyncClient) -> None:
    preview = (
        await authed.post(url("ap2", "/dhcp/preview"), json={"interface": "lan", "enabled": True})
    ).json()
    assert preview["lines"][1] == "uci -q delete dhcp.lan.ignore"
    assert preview["rollback"] is False


async def test_hosts_add_and_delete(authed: httpx.AsyncClient) -> None:
    body = {"upserts": [{"section": None, "mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.41"}], "deletes": []}
    preview = (await authed.post(url("ap1", "/hosts/preview"), json=body)).json()
    result = (
        await authed.post(url("ap1", "/hosts/apply"), json={**body, "digest": preview["digest"]})
    ).json()
    assert result["verified"]
    hosts = (await authed.get(url("ap1"))).json()["hosts"]
    added = next(h for h in hosts if h["macs"] == ["aa:bb:cc:dd:ee:01"])
    gone = {"upserts": [], "deletes": [added["section"]]}
    preview = (await authed.post(url("ap1", "/hosts/preview"), json=gone)).json()
    assert (await authed.post(url("ap1", "/hosts/apply"), json={**gone, "digest": preview["digest"]})).json()[
        "verified"
    ]


async def test_leases_and_options(authed: httpx.AsyncClient) -> None:
    leases = (await authed.get(url("ap1", "/leases"))).json()
    assert leases[0]["mac"] == PANEL and leases[0]["hostname"] == "panel"
    rows = (await authed.get(url("ap2", "/interfaces/lan/options"))).json()
    assert any(r["name"] == "ipaddr" and r["control"] == "Address" for r in rows)


async def test_access_block_now_ap1(authed: httpx.AsyncClient) -> None:
    body = {"kind": "block", "sections": ["default_radio0"], "mac": PANEL, "method": "now"}
    preview = (await authed.post(url("ap1", "/access/preview"), json=body)).json()
    assert preview["lines"] == [f"hostapd_cli -i phy0-ap0 deny_acl ADD_MAC {PANEL}"]
    result = (
        await authed.post(url("ap1", "/access/apply"), json={**body, "digest": preview["digest"]})
    ).json()
    assert result["verified"]
    access = (await authed.get(url("ap1", "/access"))).json()
    assert next(d for d in access["devices"] if d["mac"] == PANEL)["blocked_now_on"] == ["phy0-ap0"]


async def test_dns_and_routes(authed: httpx.AsyncClient) -> None:
    dns = (await authed.post(url("ap2", "/dns/preview"), json={"forwarders": ["1.1.1.1"]})).json()
    assert "uci add_list dhcp.cfg01411c.server='1.1.1.1'" in dns["lines"]
    route = {"upserts": [{"section": None, "kind": "route", "interface": "lan", "target": "10.10.0.0/16"}]}
    preview = (await authed.post(url("ap2", "/routes/preview"), json=route)).json()
    assert preview["rollback"] is True
    live = (await authed.get(url("ap2", "/routes/live"))).json()
    assert any(r["dst"] == "192.168.1.0/24" for r in live["routes"])
