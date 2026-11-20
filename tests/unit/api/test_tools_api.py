"""The Tools screen's active pages over the API, against the simulator (v1.2b)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.simwifi import SimWifi
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
    # as on AP2: the sender's seconds carry no jitter or loss, the totals do
    assert done["intervals"][0]["jitter_ms"] is None and done["intervals"][0]["lost_pct"] is None
    assert done["summary"]["jitter_ms"] == 0.05 and done["summary"]["lost_pct"] == 0


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


async def test_listen_shows_the_peer(authed: httpx.AsyncClient) -> None:
    body = {"protocol": "tcp", "port": 9100, "duration_s": 60}
    plan = (await authed.post(f"{TOOLS}/traffic/listen/preview", json=body)).json()
    assert plan["lines"][0].startswith('echo "OWG-PID $$"; exec timeout -s KILL 60 socat TCP-LISTEN:9100')
    r = await authed.post(f"{TOOLS}/traffic/listen/start", json={**body, "digest": plan["digest"]})
    assert r.status_code == 200 and r.json()["title"] == "Traffic listen"
    done = await _ended(authed, r.json()["id"])
    assert done["error"] is None and done["kind"] == "listen"
    assert done["peers"] == [
        {"address": "192.168.1.10", "port": 51515, "bytes": 6, "first_hex": "68656c6c6f0a"}
    ]


async def _send(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    plan = (await client.post(f"{TOOLS}/traffic/send/preview", json=body)).json()
    return await client.post(f"{TOOLS}/traffic/send/apply", json={**body, "digest": plan["digest"]})


async def test_send_zeros(authed: httpx.AsyncClient) -> None:
    r = await _send(authed, {"protocol": "tcp", "host": "192.168.1.10", "port": 9101, "what": "bytes"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "detail": "Sent 1000 bytes to 192.168.1.10 port 9101 over TCP."}


async def test_send_to_port_1_is_refused(authed: httpx.AsyncClient) -> None:
    r = await _send(authed, {"protocol": "tcp", "host": "192.168.1.10", "port": 1, "what": "bytes"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["detail"] == "connect(5, AF=2 192.168.1.10:1, 16): Connection refused"


async def test_send_bad_text_is_422(authed: httpx.AsyncClient) -> None:
    body = {"protocol": "tcp", "host": "192.168.1.10", "port": 9101, "what": "text", "text": "a\nb"}
    r = await authed.post(f"{TOOLS}/traffic/send/preview", json=body)
    assert r.status_code == 422 and r.json()["detail"] == "A line is 1 to 200 printable ASCII characters."


async def test_traffic_is_423_while_the_guard_is_live(authed_guard_live: httpx.AsyncClient) -> None:
    send = {"protocol": "tcp", "host": "192.168.1.10", "port": 9101, "what": "bytes"}
    assert (await _send(authed_guard_live, send)).status_code == 423
    body = {"protocol": "udp", "port": 9100, "duration_s": 60}
    plan = (await authed_guard_live.post(f"{TOOLS}/traffic/listen/preview", json=body)).json()
    r = await authed_guard_live.post(f"{TOOLS}/traffic/listen/start", json={**body, "digest": plan["digest"]})
    assert r.status_code == 423


STATION = "f4:12:fa:f3:57:68"  # the simulator's station
AP1_OWN = "02:00:00:00:00:01"
AP2_OWN = "02:00:00:00:00:02"
NOT_SUPPORTED_TRANSITION = (
    "hostapd on AP2 · office says Not supported. BSS transition needs bss_transition on this SSID: "
    "Wi-Fi › All options › bss_transition."
)


async def _ap2_on_air(ctx: AppContext) -> None:
    """AP2's radio up in the simulator (it is parked there), as a second router with an SSID on air."""
    rec = ctx.routers.get("ap2")
    assert rec is not None
    t = await ctx.pool.get(rec)
    assert t.state is not None and t.state.wifi is not None  # type: ignore[attr-defined]
    t.state.wifi._up["radio0"] = True  # type: ignore[attr-defined]  # noqa: SLF001


async def _station(client: httpx.AsyncClient, router: str, body: dict[str, Any]) -> httpx.Response:
    plan = await client.post(f"/api/routers/{router}/tools/stations/preview", json=body)
    assert plan.status_code == 200, plan.text
    return await client.post(
        f"/api/routers/{router}/tools/stations/apply", json={**body, "digest": plan.json()["digest"]}
    )


async def test_stations_view(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await _ap2_on_air(ctx)
    view = (await authed.get(f"{TOOLS}/stations")).json()
    ap = view["aps"][0]
    assert (ap["ifname"], ap["ssid"], ap["channel"]) == ("phy0-ap0", "OpenWrt", 1)
    assert ap["methods"] == [
        "bss_transition_request",
        "rrm_nr_get_own",
        "rrm_nr_list",
        "rrm_nr_set",
        "rrm_beacon_req",
    ]
    assert ap["own"]["bssid"] == AP1_OWN and ap["neighbours"] == []
    assert [s["mac"] for s in ap["stations"]] == [STATION]
    sources = {c["bssid"]: c["source"] for c in view["candidates"]}
    assert sources == {AP1_OWN: "AP1 · bench · OpenWrt", AP2_OWN: "AP2 · office · OpenWrt"}


async def test_candidates_come_only_from_routers_online(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review (I4): a router the app has not reached is not connected to for its candidates (each
    unreachable one would add a connect wait to the view, the preview and the apply)."""
    await _ap2_on_air(ctx)
    asked: list[str] = []
    real_get = ctx.pool.get

    async def get(rec: Any, *, token: object | None = None) -> Any:
        asked.append(rec.id)
        return await real_get(rec, token=token)

    monkeypatch.setattr(ctx.pool, "get", get)
    view = (await authed.get(f"{TOOLS}/stations")).json()
    assert set(asked) == {"ap1", "ap2"}, asked
    assert AP2_OWN in {c["bssid"] for c in view["candidates"]}


async def test_neighbours_set_and_clear(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await _ap2_on_air(ctx)
    body = {"kind": "neighbours", "ifname": "phy0-ap0", "neighbours": [AP2_OWN]}
    plan = (await authed.post(f"{TOOLS}/stations/preview", json=body)).json()
    assert plan["lines"][0].startswith(
        'ubus call hostapd.phy0-ap0 rrm_nr_set \'{"list":[["02:00:00:00:00:02"'
    )
    assert "Kept until the next Wi-Fi reload: hostapd does not save it." in plan["warnings"]
    r = await _station(authed, "ap1", body)
    assert r.status_code == 200 and r.json()["ok"], r.text
    ap = (await authed.get(f"{TOOLS}/stations")).json()["aps"][0]
    assert [n["bssid"] for n in ap["neighbours"]] == [AP2_OWN]
    r = await _station(authed, "ap1", {"kind": "neighbours", "ifname": "phy0-ap0", "neighbours": []})
    assert r.json()["ok"] and (await authed.get(f"{TOOLS}/stations")).json()["aps"][0]["neighbours"] == []


async def test_an_ap_is_not_its_own_neighbour(authed: httpx.AsyncClient) -> None:
    """AP2 window (2026-11-20): hostapd keeps an AP's own report out of its neighbour list, so setting it
    there would show nothing; the request is refused before anything is sent."""
    body = {"kind": "neighbours", "ifname": "phy0-ap0", "neighbours": [AP1_OWN]}
    r = await authed.post(f"{TOOLS}/stations/preview", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == (
        f"{AP1_OWN} is this SSID's own BSSID: hostapd keeps its own report apart, not in its neighbour list."
    )


async def test_bss_transition(authed: httpx.AsyncClient) -> None:
    body = {"kind": "transition", "ifname": "phy0-ap0", "mac": STATION, "target": AP1_OWN}
    plan = (await authed.post(f"{TOOLS}/stations/preview", json=body)).json()
    assert (
        plan["lines"][1]
        == "timeout -s KILL 12 ubus subscribe hostapd.phy0-ap0  # 10 s, for the station's answer"
    )
    result = (await _station(authed, "ap1", body)).json()
    assert result["ok"] and result["status_code"] == 0, result
    assert result["events"][0]["fields"]["address"] == STATION


async def test_beacon_report(authed: httpx.AsyncClient) -> None:
    body = {"kind": "beacon", "ifname": "phy0-ap0", "mac": STATION}
    result = (await _station(authed, "ap1", body)).json()
    assert result["ok"], result
    assert [(b["channel"], b["rcpi_dbm"], b["rsni"]) for b in result["beacons"]] == [(11, -50.0, 40)]


async def test_hostapd_refusals(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await _ap2_on_air(ctx)
    body = {"kind": "transition", "ifname": "phy0-ap0", "mac": STATION, "target": AP2_OWN}
    result = (await _station(authed, "ap2", body)).json()
    assert result == {
        "ok": False,
        "detail": NOT_SUPPORTED_TRANSITION,
        "events": [],
        "beacons": [],
        "status_code": None,
    }
    beacon = (await _station(authed, "ap2", {"kind": "beacon", "ifname": "phy0-ap0", "mac": STATION})).json()
    assert beacon["detail"] == (
        "hostapd on AP2 · office says Not supported. The beacon report needs ieee80211k on this SSID: "
        "Wi-Fi › All options › ieee80211k."
    )


async def test_a_station_that_is_not_connected(authed: httpx.AsyncClient) -> None:
    body = {"kind": "beacon", "ifname": "phy0-ap0", "mac": "02:00:00:00:00:99"}
    r = await authed.post(f"{TOOLS}/stations/preview", json=body)
    assert (
        r.status_code == 422 and r.json()["detail"] == "02:00:00:00:00:99 is no longer connected to OpenWrt."
    )


async def test_no_answer_from_the_station(authed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SimWifi, "_answer", lambda self, ifname, event: None)
    result = (await _station(authed, "ap1", {"kind": "beacon", "ifname": "phy0-ap0", "mac": STATION})).json()
    assert result["ok"] is True and result["detail"] == "No answer from the station in 10 s."
    assert result["beacons"] == []


async def test_station_requests_are_423_while_the_guard_is_live(authed_guard_live: httpx.AsyncClient) -> None:
    r = await _station(authed_guard_live, "ap1", {"kind": "beacon", "ifname": "phy0-ap0", "mac": STATION})
    assert r.status_code == 423


async def test_unknown_router_is_404(authed: httpx.AsyncClient) -> None:
    r = await authed.get("/api/routers/nope/tools/sessions")
    assert r.status_code == 404
