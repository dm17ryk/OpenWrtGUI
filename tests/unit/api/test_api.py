from __future__ import annotations

import io
import zipfile
from typing import Any

import httpx
import pytest
from apiconst import BASE, TOKEN, WS
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openwrtgui.app import create_app
from openwrtgui.context import AppContext
from openwrtgui.onboard.wizard import install_key_command
from openwrtgui.version import APP_VERSION


async def test_token_required(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/routers")).status_code == 401
    r = await client.get("/api/routers", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_wrong_host_rejected(authed: httpx.AsyncClient) -> None:
    r = await authed.get("/api/routers", headers={"Host": "evil.example:80"})
    assert r.status_code == 400


async def test_health_without_token(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/health")).json()
    assert body["version"] == APP_VERSION and body["status"] == "ok" and body["mode"] == "simulator"


async def test_routers_list_has_three_sim_routers(authed: httpx.AsyncClient) -> None:
    items = (await authed.get("/api/routers")).json()
    assert [i["record"]["id"] for i in items] == ["ap1", "ap2", "ap3"]
    assert next(i for i in items if i["record"]["id"] == "ap3")["record"]["auth"] == "none"


async def test_router_list_carries_cached_summary(authed: httpx.AsyncClient) -> None:
    await authed.post("/api/routers/ap2/describe")
    items = {i["record"]["id"]: i for i in (await authed.get("/api/routers")).json()}
    assert items["ap2"]["summary"]["revision"] == "r35692-b8bffeefdf"
    assert items["ap1"]["summary"] is None


async def test_router_detail_describes_on_demand(authed: httpx.AsyncClient) -> None:
    detail = (await authed.get("/api/routers/ap2")).json()
    assert detail["summary"]["model"] == "D-Link DWR-921 C3 (U-Boot)"
    assert detail["summary"]["wireless_options"]["radio0"]["interface"] == 289
    assert (await authed.get("/api/routers/nope")).status_code == 404


async def test_onboard_flow_over_api(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    v = (await authed.post("/api/onboard", json={"host": "192.168.1.4"})).json()
    sid, fp = v["sid"], v["host_key"]["fingerprint"]
    assert (await authed.post(f"/api/onboard/{sid}/trust", json={"fingerprint": fp})).status_code == 200
    r = await authed.post(f"/api/onboard/{sid}/login", json={"password": "wrong"})
    assert r.status_code == 403 and r.json()["detail"] == "The router refused the login."
    v = (await authed.post(f"/api/onboard/{sid}/login", json={"password": "sim-password"})).json()
    assert v["step"] == "install_key"
    preview = (await authed.get(f"/api/onboard/{sid}/install-key/preview")).json()
    assert preview == {"commands": [install_key_command(ctx.app_key.public_line)]}
    assert (await authed.post(f"/api/onboard/{sid}/install-key")).status_code == 200
    assert (await authed.post(f"/api/onboard/{sid}/verify")).json()["key_installed"] is True
    v = (await authed.post(f"/api/onboard/{sid}/identify")).json()
    assert v["proposed_port_labels"]["0"] == "LAN4"
    rec = (
        await authed.post(
            f"/api/onboard/{sid}/finish", json={"name": "AP4 · test", "port_labels": {"0": "LAN4"}}
        )
    ).json()
    assert rec["id"] == "ap4-test" and rec["auth"] == "key"
    assert len((await authed.get("/api/routers")).json()) == 4
    assert (await authed.post(f"/api/onboard/{sid}/verify")).status_code == 404


async def test_install_key_423_during_run(authed_guard_live: httpx.AsyncClient) -> None:
    v = (await authed_guard_live.post("/api/onboard", json={"host": "192.168.1.4"})).json()
    sid = v["sid"]
    await authed_guard_live.post(
        f"/api/onboard/{sid}/trust", json={"fingerprint": v["host_key"]["fingerprint"]}
    )
    await authed_guard_live.post(f"/api/onboard/{sid}/login", json={"password": "sim-password"})
    r = await authed_guard_live.post(f"/api/onboard/{sid}/install-key")
    assert r.status_code == 423
    body = r.json()
    assert body["detail"] == "dima_night.py started 21:04 (PID 18244)" and body["guard"]["live"] is True


async def test_guard_endpoint(authed_guard_live: httpx.AsyncClient) -> None:
    g = (await authed_guard_live.get("/api/guard")).json()
    assert g["live"] and g["reasons"][0]["text"] == "dima_night.py started 21:04 (PID 18244)"


async def test_settings_put_validates_theme(authed: httpx.AsyncClient) -> None:
    s = (await authed.get("/api/settings")).json()
    assert (await authed.put("/api/settings", json={**s, "theme": "blue"})).status_code == 422
    r = await authed.put("/api/settings", json={**s, "theme": "dark"})
    assert r.status_code == 200 and (await authed.get("/api/settings")).json()["theme"] == "dark"


async def test_audit_query_and_export(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.audit.record(router="ap2", screen="Terminal", command="uname -a", exit_status=0, source="terminal")
    entries = (await authed.get("/api/audit", params={"router": "ap2"})).json()
    assert entries[0]["command"] == "uname -a"
    r = await authed.get("/api/audit/export")
    assert r.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist()


async def test_app_key_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    k = (await authed.get("/api/app-key")).json()
    assert k["fingerprint"] == ctx.app_key.fingerprint
    r = await authed.get("/api/app-key/public")
    assert r.text.strip() == ctx.app_key.public_line and "attachment" in r.headers["content-disposition"]


async def test_update_check_offers_fixture_release(authed: httpx.AsyncClient) -> None:
    status = (await authed.post("/api/update/check")).json()
    assert status["available"] and status["latest"]["version"] == "0.1.0" and status["can_install"] is False


async def test_update_install_asks_when_terminals_open(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.terminals.add(object())  # type: ignore[arg-type]
    r = await authed.post("/api/update/install", json={"version": "0.1.0"})
    assert r.status_code == 409 and r.json()["open_terminals"] == 1


async def test_quit_sets_event(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    assert (await authed.post("/api/app/quit")).status_code == 200
    assert ctx.quit_event.is_set()


def _ws_client(ctx: AppContext) -> TestClient:
    return TestClient(create_app(ctx), base_url=BASE)


def test_ws_live_requires_token_and_sends_guard_first(ctx: AppContext) -> None:
    tc = _ws_client(ctx)
    with pytest.raises(WebSocketDisconnect) as refused, tc.websocket_connect(f"{WS}/ws/live") as ws:
        ws.receive_json()
    assert refused.value.code == 4401
    with tc.websocket_connect(f"{WS}/ws/live?t={TOKEN}") as ws:
        first: dict[str, Any] = ws.receive_json()
        assert first["type"] == "guard" and first["state"]["live"] is False


def test_ws_rejects_foreign_origin(ctx: AppContext) -> None:
    tc = _ws_client(ctx)
    url = f"{WS}/ws/live?t={TOKEN}"
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        tc.websocket_connect(url, headers={"Origin": "http://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert refused.value.code == 4403


def test_ws_terminal_line_mode_in_simulator(ctx: AppContext) -> None:
    tc = _ws_client(ctx)
    with tc.websocket_connect(f"{WS}/ws/terminal/ap2?t={TOKEN}") as ws:
        assert ws.receive_json()["mode"] == "line"
        ws.send_json({"type": "line", "text": "cat /etc/board.json"})
        out = ws.receive_json()
        assert out["type"] == "output" and "dwr-921" in out["data"]
        assert ws.receive_json() == {"type": "exit", "status": 0}
