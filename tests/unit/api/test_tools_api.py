"""The Tools screen's active pages over the API, against the simulator (v1.2b)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from openwrtgui.tools.throughput import CPU_WARNING, HOST_TEXT

TOOLS = "/api/routers/ap1/tools"


async def _ended(authed: httpx.AsyncClient, session_id: str) -> dict[str, Any]:
    for _ in range(500):
        sessions = (await authed.get(f"{TOOLS}/sessions")).json()
        view = next(s for s in sessions if s["id"] == session_id)
        if not view["running"]:
            return dict(view)
        await asyncio.sleep(0.01)
    raise AssertionError("the session did not end")


async def _throughput(authed: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    plan = (await authed.post(f"{TOOLS}/throughput/preview", json=body)).json()
    r = await authed.post(f"{TOOLS}/throughput/start", json={**body, "digest": plan["digest"]})
    assert r.status_code == 200, r.text
    return await _ended(authed, r.json()["id"])


async def test_throughput_preview(authed: httpx.AsyncClient) -> None:
    r = await authed.post(f"{TOOLS}/throughput/preview", json={"mode": "client", "host": "192.168.1.10"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["lines"] == [
        'echo "OWG-PID $$"; exec timeout -s KILL 25 '
        "iperf3 -c 192.168.1.10 -p 5201 -t 10 -J --json-stream --forceflush 2>&1"
    ]
    assert CPU_WARNING in plan["warnings"]


async def test_server_preview_has_the_hint(authed: httpx.AsyncClient) -> None:
    plan = (await authed.post(f"{TOOLS}/throughput/preview", json={"mode": "server", "port": 5202})).json()
    assert (
        "From your PC: iperf3 -c 192.168.1.1 -p 5202. The router waits up to 5 minutes for one test."
        in plan["warnings"]
    )


async def test_throughput_runs_to_a_summary(authed: httpx.AsyncClient) -> None:
    done = await _throughput(authed, {"mode": "client", "host": "192.168.1.10"})
    assert done["error"] is None and len(done["intervals"]) == 10
    assert done["intervals"][0]["mbps"] == 94.2 and done["intervals"][0]["retransmits"] == 0
    assert done["summary"]["sent_mbps"] == 94.2 and done["summary"]["cpu_pct"] is not None


async def test_udp_throughput_at_the_asked_rate(authed: httpx.AsyncClient) -> None:
    body = {"mode": "client", "host": "pc.lan", "protocol": "udp", "udp_mbps": 20, "duration_s": 3}
    done = await _throughput(authed, body)
    assert [i["mbps"] for i in done["intervals"]] == [20.0, 20.0, 20.0]
    assert done["intervals"][0]["jitter_ms"] == 0.05 and done["intervals"][0]["lost_pct"] == 0


async def test_server_gets_one_test(authed: httpx.AsyncClient) -> None:
    done = await _throughput(authed, {"mode": "server"})
    assert done["error"] is None and len(done["intervals"]) == 5 and done["summary"] is not None


async def test_port_1_is_refused(authed: httpx.AsyncClient) -> None:
    done = await _throughput(authed, {"mode": "client", "host": "192.168.1.10", "port": 1})
    assert done["error"].startswith("iperf3: unable to connect to server")
    assert done["error"].endswith("Connection refused")


async def test_a_wrong_digest_is_409(authed: httpx.AsyncClient) -> None:
    body = {"mode": "client", "host": "192.168.1.10", "digest": "0" * 16}
    r = await authed.post(f"{TOOLS}/throughput/start", json=body)
    assert r.status_code == 409 and "changed since the preview" in r.json()["detail"]


async def test_a_hostile_host_is_refused(authed: httpx.AsyncClient) -> None:
    r = await authed.post(f"{TOOLS}/throughput/preview", json={"mode": "client", "host": "x; reboot"})
    assert r.status_code == 422 and r.json()["detail"] == HOST_TEXT


async def test_live_guard_is_423(authed_guard_live: httpx.AsyncClient) -> None:
    body = {"mode": "client", "host": "192.168.1.10"}
    plan = (await authed_guard_live.post(f"{TOOLS}/throughput/preview", json=body)).json()
    r = await authed_guard_live.post(f"{TOOLS}/throughput/start", json={**body, "digest": plan["digest"]})
    assert r.status_code == 423


async def test_stop_a_session(authed: httpx.AsyncClient) -> None:
    done = await _throughput(authed, {"mode": "server"})
    r = await authed.post(f"{TOOLS}/sessions/{done['id']}/stop")
    assert r.status_code == 200 and r.json()["running"] is False
    r = await authed.post("/api/routers/ap2/tools/sessions/" + done["id"] + "/stop")
    assert r.status_code == 404


async def test_unknown_router_is_404(authed: httpx.AsyncClient) -> None:
    r = await authed.get("/api/routers/nope/tools/sessions")
    assert r.status_code == 404
