"""The VLAN editor on a DSA router (v1.0a3): state, exact previews, applies with the 60 s rollback (D3 layer
2), proof by netifd's own report of the bridge's VLANs (D4)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from typing import Any

from openwrtgui.net import commands as c
from openwrtgui.net.apply import (
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    net_plan,
    rollback_warning,
)
from openwrtgui.net.service import network_snapshot
from openwrtgui.net.state import read_network
from openwrtgui.ports.bridge import BridgeState, LiveVlan, live_vlans
from openwrtgui.ports.bridge_rules import BridgeChange, BridgeVlanRequest, bridge_change
from openwrtgui.ports.bridge_state import read_bridge
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Ports"
SETTLE_S = 10.0
POLL_S = 1.0


def _differs(want: Sequence[LiveVlan], now: Sequence[LiveVlan] | None) -> str:
    if now is None:
        return "its report could not be read"
    asked, got = {v.vlan: v for v in want}, {v.vlan: v for v in now}
    ids = sorted(v for v in {*asked, *got} if asked.get(v) != got.get(v))
    return ", ".join(f"VLAN {v}" for v in ids) or "no VLANs reported"


class BridgeVlanService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        descriptions: MutableMapping[str, SelfDescription],
        runner: ApplyRunner,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        settle_s: float = SETTLE_S,
        poll_s: float = POLL_S,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._descriptions = descriptions
        self._runner = runner
        self._sleep = sleep
        self._settle_s = settle_s
        self._poll_s = poll_s

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _read_on(self, rec: RouterRecord, t: Transport) -> tuple[BridgeState, dict[str, str]]:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        net, uci = await read_network(t, rec.id, desc)
        return await read_bridge(t, rec, desc, net, uci), uci

    async def state(self, router_id: str) -> BridgeState:
        rec = self._record(router_id)
        return (await self._read_on(rec, await self._pool.get(rec)))[0]

    def _plan(
        self,
        rec: RouterRecord,
        state: BridgeState,
        uci: Mapping[str, str],
        upserts: Sequence[BridgeVlanRequest],
        deletes: Sequence[str],
    ) -> tuple[NetPlan, BridgeChange]:
        change = bridge_change(state, upserts, deletes, rec.name)
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="network",
            ops=change.ops,
            current=uci,
            rollback=True,
            warnings=[*change.warnings, rollback_warning(rec.name, rec.host)],
        )
        return plan, change

    async def plan(
        self, router_id: str, upserts: Sequence[BridgeVlanRequest], deletes: Sequence[str]
    ) -> NetPlan:
        rec = self._record(router_id)
        state, uci = await self._read_on(rec, await self._pool.get(rec))
        return self._plan(rec, state, uci, upserts, deletes)[0]

    async def apply(
        self,
        router_id: str,
        upserts: Sequence[BridgeVlanRequest],
        deletes: Sequence[str],
        digest: str | None = None,
    ) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            state, uci = await self._read_on(rec, t)
            plan, change = self._plan(rec, state, uci, upserts, deletes)
            assert state.bridge is not None  # bridge_change refuses a router without one
            ports = frozenset(p.name for p in state.ports)
            return Planned(plan, self._verify(state.bridge, ports, change.want), network_snapshot(uci))

        return await self._runner.run_planned(rec, make, digest)

    def _verify(
        self, bridge: str, ports: frozenset[str], want: tuple[LiveVlan, ...]
    ) -> Callable[[Transport], Awaitable[list[NetCheck]]]:
        async def live(t2: Transport) -> tuple[LiveVlan, ...] | None:
            r = await t2.run(c.DEVICE_STATUS)
            return live_vlans(r.stdout, bridge, ports) if r.ok else None  # a failed read proves nothing

        async def verify(t2: Transport) -> list[NetCheck]:
            now = await live(t2)
            for _ in range(int(self._settle_s / self._poll_s)):
                if now == want:
                    break
                await self._sleep(self._poll_s)
                now = await live(t2)
            if now == want:
                return [NetCheck("bridge", True, f"{bridge} has the VLANs as asked")]
            return [NetCheck("bridge", False, f"{bridge} differs: {_differs(want, now)}")]

        return verify
