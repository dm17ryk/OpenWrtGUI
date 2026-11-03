from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.live import LiveHub
from openwrtgui.poller import StatusPoller
from openwrtgui.probe.commands import WIRELESS_STATUS
from openwrtgui.probe.status import RouterStatus
from openwrtgui.simulator import sim_commands
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import CommandResult, Transport, Unreachable
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.transport.pool import ConnectionPool

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"


def _rec(router_id: str, auth: str = "key") -> RouterRecord:
    return RouterRecord(
        id=router_id, name=router_id, host=f"h-{router_id}", auth=auth, added_at=datetime(2026, 11, 3)
    )  # type: ignore[arg-type]


def _drain(q: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _poller(
    tmp_path: Path, factory: Any, guard: BenchGuard | None = None, records: list[RouterRecord] | None = None
):
    store = RouterStore(tmp_path / "routers.json")
    for r in records or [_rec("ap1")]:
        store.upsert(r)
    hub = LiveHub()
    statuses: dict[str, RouterStatus] = {}
    g = guard or BenchGuard(GuardWatchList(lock_files=[], processes=[]), lister=lambda: [])
    poller = StatusPoller(routers=store, pool=ConnectionPool(factory), guard=g, hub=hub, statuses=statuses)
    return poller, hub, statuses, store, g


async def test_poll_publishes_status_with_station(tmp_path: Path) -> None:
    async def factory(rec: RouterRecord) -> Transport:
        return ReplayTransport(sim_commands(SIM_DIR, "ap1"))

    poller, hub, statuses, store, _ = _poller(tmp_path, factory)
    q = hub.subscribe()
    rec = store.get("ap1")
    assert rec is not None
    await poller.poll_router(rec)
    msgs = _drain(q)
    assert [m["type"] for m in msgs] == ["status"]
    assert msgs[0]["router"] == "ap1"
    assert len(msgs[0]["status"].radios[0].stations) == 1
    assert statuses["ap1"].radios[0].up


async def test_run_ssid_on_air_makes_guard_live(tmp_path: Path) -> None:
    commands = sim_commands(SIM_DIR, "ap1")
    status = commands[WIRELESS_STATUS]
    commands[WIRELESS_STATUS] = CommandResult(
        WIRELESS_STATUS, status.stdout.replace('"OpenWrt"', '"OpenWrtB"'), "", 0
    )

    async def factory(rec: RouterRecord) -> Transport:
        return ReplayTransport(commands)

    guard = BenchGuard(
        GuardWatchList(lock_files=[], processes=[], router_ssids=["OpenWrtB"]), lister=lambda: []
    )
    poller, hub, *_ = _poller(tmp_path, factory, guard=guard)
    rec = RouterStore(tmp_path / "routers.json").get("ap1")
    assert rec is not None
    await poller.poll_router(rec)
    await poller.check_guard()
    state = guard.state()
    assert state.live and state.reasons[0].kind == "router_ssid" and state.reasons[0].router == "ap1"


async def test_poll_marks_offline_and_keeps_others(tmp_path: Path) -> None:
    async def factory(rec: RouterRecord) -> Transport:
        if rec.id == "ap2":
            raise Unreachable("192.168.1.2:22: timed out")
        return ReplayTransport(sim_commands(SIM_DIR, "ap3"))

    poller, hub, statuses, store, _ = _poller(tmp_path, factory, records=[_rec("ap2"), _rec("ap3")])
    q = hub.subscribe()
    await poller.poll_all()
    msgs = {m["router"]: m for m in _drain(q)}
    assert msgs["ap2"]["type"] == "router-offline" and "timed out" in msgs["ap2"]["error"]
    assert msgs["ap3"]["type"] == "status"
    assert "ap3" in statuses and "ap2" not in statuses


async def test_failure_mid_read_drops_the_connection(tmp_path: Path) -> None:
    class Broken(ReplayTransport):
        async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
            raise Unreachable("connection lost")

    made = 0

    async def factory(rec: RouterRecord) -> Transport:
        nonlocal made
        made += 1
        return Broken({})

    poller, hub, *_ = _poller(tmp_path, factory)
    rec = RouterStore(tmp_path / "routers.json").get("ap1")
    assert rec is not None
    await poller.poll_router(rec)
    assert not poller.pool.health("ap1").online


async def test_guard_message_only_on_change(tmp_path: Path) -> None:
    procs: list[ProcessInfo] = []
    guard = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: procs)

    async def factory(rec: RouterRecord) -> Transport:
        return ReplayTransport({})

    poller, hub, *_ = _poller(tmp_path, factory, guard=guard)
    q = hub.subscribe()
    for _ in range(3):
        await poller.check_guard()
    assert [m["type"] for m in _drain(q)] == ["guard"]
    procs.append(ProcessInfo(1, ("dima_night.py",), datetime(2026, 11, 3, 21, 4)))
    await poller.check_guard()
    await poller.check_guard()
    msgs = _drain(q)
    assert len(msgs) == 1 and msgs[0]["state"].live


async def test_routers_without_key_are_not_polled(tmp_path: Path) -> None:
    async def factory(rec: RouterRecord) -> Transport:
        raise AssertionError("must not connect")

    poller, hub, *_ = _poller(tmp_path, factory, records=[_rec("ap3", auth="none")])
    await poller.poll_all()


def test_hub_snapshot_keeps_latest_per_router() -> None:
    hub = LiveHub()
    hub.publish({"type": "guard", "state": 1})
    hub.publish({"type": "status", "router": "ap1", "status": 1})
    hub.publish({"type": "router-offline", "router": "ap1", "since": "x", "error": "e"})
    hub.publish({"type": "status", "router": "ap2", "status": 2})
    snap = hub.snapshot()
    assert [m["type"] for m in snap] == ["guard", "router-offline", "status"]


def test_full_queue_drops_oldest() -> None:
    hub = LiveHub()
    q = hub.subscribe()
    for i in range(105):
        hub.publish({"type": "status", "router": "ap1", "status": i})
    assert q.qsize() == 100 and q.get_nowait()["status"] == 5
    hub.unsubscribe(q)
    hub.publish({"type": "guard", "state": 0})
    assert q.qsize() == 99  # one item was taken above; nothing new arrives after unsubscribe
