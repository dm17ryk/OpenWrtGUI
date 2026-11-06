"""The Ports screen: reads, exact previews, applies, proof by effect. Port enable is runtime swconfig (lost on
the next reboot or network reload); VLANs and the mirror are `network` changes with the rollback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net import commands as c
from openwrtgui.net.apply import ApplyRunner, NetApplyResult, NetCheck, NetPlan, net_plan, rollback_warning
from openwrtgui.net.service import as_previewed, network_snapshot
from openwrtgui.net.state import read_network
from openwrtgui.ports.compile import (
    MirrorRequest,
    VlanRequest,
    compile_mirror,
    compile_vlans,
    enable_all_commands,
    enable_commands,
)
from openwrtgui.ports.model import SwitchLive
from openwrtgui.ports.parse import parse_members, parse_swconfig_show
from openwrtgui.ports.state import PortsState, read_ports
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import drop_unchanged

SCREEN = "Ports"
SETTLE_S = 10.0
POLL_S = 1.0
RUNTIME_NOTE = "A port turned off here stays off until the next reboot or network reload."


class PortsService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        descriptions: MutableMapping[str, SelfDescription],
        runner: ApplyRunner,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        settle_s: float = SETTLE_S,
        poll_s: float = POLL_S,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._descriptions = descriptions
        self._runner = runner
        self._sleep = sleep
        self._settle_s = settle_s
        self._poll_s = poll_s

    async def _read(self, router_id: str) -> tuple[RouterRecord, Transport, PortsState, dict[str, str]]:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        t = await self._pool.get(rec)
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        net, uci = await read_network(t, rec.id, desc)
        return rec, t, await read_ports(t, rec, desc, net, uci), uci

    async def state(self, router_id: str) -> PortsState:
        return (await self._read(router_id))[2]

    async def _show(self, t: Transport, state: PortsState) -> SwitchLive:
        assert state.switch is not None
        return parse_swconfig_show(state.switch, (await t.run(c.swconfig_show(state.switch))).stdout)

    async def _poll(self, t: Transport, state: PortsState, ok: Callable[[SwitchLive], bool]) -> SwitchLive:
        live = await self._show(t, state)
        for _ in range(int(self._settle_s / self._poll_s)):
            if ok(live):
                break
            await self._sleep(self._poll_s)
            live = await self._show(t, state)
        return live

    # ---------------------------------------------------------------- port enable (runtime)
    def _ports_plan(
        self,
        rec: RouterRecord,
        state: PortsState,
        uci: Mapping[str, str],
        port: int | None,
        on: bool | None,
        all_on: bool,
    ) -> NetPlan:
        if all_on:
            commands = enable_all_commands(state)
        else:
            if port is None or on is None:
                raise ValueError("Choose a port and on or off")
            commands = enable_commands(state, port, on, rec.name)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current=uci,
            commands=commands,
            warnings=[RUNTIME_NOTE] if not all_on and on is False else [],
        )

    async def plan_ports(
        self, router_id: str, port: int | None, on: bool | None, *, all_on: bool = False
    ) -> NetPlan:
        rec, _t, state, uci = await self._read(router_id)
        return self._ports_plan(rec, state, uci, port, on, all_on)

    async def apply_ports(
        self,
        router_id: str,
        port: int | None,
        on: bool | None,
        digest: str | None = None,
        *,
        all_on: bool = False,
    ) -> NetApplyResult:
        rec, t, state, uci = await self._read(router_id)
        plan = as_previewed(rec, self._ports_plan(rec, state, uci, port, on, all_on), digest)
        asked = {int(cmd.split()[4]): cmd.endswith(" 1") for cmd in plan.commands}

        async def verify(t2: Transport) -> list[NetCheck]:
            def holds(live: SwitchLive) -> bool:
                now = {p.num: p for p in live.ports}
                return all(
                    n in now and now[n].enabled == want and (want or not now[n].link)
                    for n, want in asked.items()
                )

            live = {p.num: p for p in (await self._poll(t2, state, holds)).ports}
            checks = []
            for n, want in asked.items():
                label = next((p.label for p in state.ports if p.num == n), f"port {n}")
                got = live.get(n)
                good = got is not None and got.enabled == want and (want or not got.link)
                detail = ("on" if want else "off, no link") if good else "not as asked"
                checks.append(NetCheck(f"port {label}", good, detail))
            return checks

        return await self._runner.run(rec, t, plan, verify)

    # ---------------------------------------------------------------- VLANs (rollback)
    def _vlans_plan(
        self,
        rec: RouterRecord,
        state: PortsState,
        uci: Mapping[str, str],
        upserts: Sequence[VlanRequest],
        deletes: Sequence[str],
    ) -> NetPlan:
        ops, warnings = compile_vlans(upserts, deletes, state)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="network",
            ops=ops,
            current=uci,
            rollback=True,
            warnings=[*warnings, rollback_warning(rec.name, rec.host)],
        )

    async def plan_vlans(
        self, router_id: str, upserts: Sequence[VlanRequest], deletes: Sequence[str]
    ) -> NetPlan:
        rec, _t, state, uci = await self._read(router_id)
        return self._vlans_plan(rec, state, uci, upserts, deletes)

    async def apply_vlans(
        self,
        router_id: str,
        upserts: Sequence[VlanRequest],
        deletes: Sequence[str],
        digest: str | None = None,
    ) -> NetApplyResult:
        rec, t, state, uci = await self._read(router_id)
        plan = as_previewed(rec, self._vlans_plan(rec, state, uci, upserts, deletes), digest)
        want = {
            u.vlan: parse_members(
                " ".join(f"{p}{'t' if cell == 't' else ''}" for p, cell in u.members.items())
            )
            for u in upserts
        }
        gone = {v.vlan for v in state.vlans if v.section in deletes}

        def holds(live: SwitchLive) -> bool:
            now = {v.vlan: v.members for v in live.vlans}
            return all(now.get(n) == m for n, m in want.items()) and not (gone & set(now))

        async def verify(t2: Transport) -> list[NetCheck]:
            ok = holds(await self._poll(t2, state, holds))
            return [
                NetCheck("switch", ok, "the switch has the VLANs as asked" if ok else "the switch differs")
            ]

        return await self._runner.run(rec, t, plan, verify, network_snapshot(uci))

    # ---------------------------------------------------------------- switch port mirror (rollback)
    def _mirror_plan(
        self, rec: RouterRecord, state: PortsState, uci: Mapping[str, str], req: MirrorRequest
    ) -> NetPlan:
        ops = compile_mirror(req, state, uci)
        # A reload sets the monitor port only when the config names one, so off puts it back by hand
        # (AP2, 2026-11-06: it stayed at 1 after the mirror was off).
        off = req.monitor is None and drop_unchanged(ops, uci) and state.switch is not None
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="network",
            ops=ops,
            current=uci,
            commands=[f"swconfig dev {state.switch} set mirror_monitor_port 0"] if off else [],
            rollback=True,
            warnings=[rollback_warning(rec.name, rec.host)],
        )

    async def plan_mirror(self, router_id: str, req: MirrorRequest) -> NetPlan:
        rec, _t, state, uci = await self._read(router_id)
        return self._mirror_plan(rec, state, uci, req)

    async def apply_mirror(
        self, router_id: str, req: MirrorRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec, t, state, uci = await self._read(router_id)
        plan = as_previewed(rec, self._mirror_plan(rec, state, uci, req), digest)
        sources = {p: f for p, f in req.sources.items() if f[0] or f[1]} if req.monitor is not None else {}

        def holds(live: SwitchLive) -> bool:
            flags = {p.num: (p.mirror_rx, p.mirror_tx) for p in live.ports if p.mirror_rx or p.mirror_tx}
            monitor_ok = live.mirror_monitor_port == (req.monitor if req.monitor is not None else 0)
            return flags == sources and monitor_ok

        async def verify(t2: Transport) -> list[NetCheck]:
            ok = holds(await self._poll(t2, state, holds))
            return [NetCheck("switch", ok, "the switch mirrors as asked" if ok else "the switch differs")]

        return await self._runner.run(rec, t, plan, verify, network_snapshot(uci))
