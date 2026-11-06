"""The Firewall screen: reads, exact previews, applies with the 60 s rollback, proof by effect."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from typing import Any

from openwrtgui.fw import commands as c
from openwrtgui.fw.compile import (
    ForwardingRequest,
    ModelRequest,
    ZoneRequest,
    compile_model,
    compile_zones,
    zone_policies,
)
from openwrtgui.fw.model import Direction, Policy
from openwrtgui.fw.nft import Ruleset, parse_ruleset_json, zone_tail
from openwrtgui.fw.sections import Kind, SectionRequest, compile_sections, expectations
from openwrtgui.fw.state import PIN_DHCP, PIN_SSH, FirewallState, read_firewall
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import (
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    Snapshot,
    net_plan,
    rollback_warning,
    saved_check,
)
from openwrtgui.net.state import NetworkState, read_network
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import SettingsStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import UciOp

SCREEN = "Firewall"
SETTLE_S = 10.0
POLL_S = 1.0
PIN_NAMES = {PIN_SSH: "Allow SSH from this PC", PIN_DHCP: "Allow DHCP and DNS"}


def firewall_snapshot(uci: Mapping[str, str]) -> Snapshot:
    return Snapshot(c.UCI_FIREWALL, {k: v for k, v in uci.items() if k.startswith("firewall.")})


class FirewallService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        settings: SettingsStore,
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
        self._settings = settings
        self._descriptions = descriptions
        self._runner = runner
        self._sleep = sleep
        self._settle_s = settle_s
        self._poll_s = poll_s

    # ---------------------------------------------------------------- reading
    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _read_on(
        self, rec: RouterRecord, t: Transport
    ) -> tuple[FirewallState, dict[str, str], Ruleset, NetworkState]:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        net, _ = await read_network(t, rec.id, desc)
        known = self._settings.load().known_tables
        state, uci, ruleset = await read_firewall(t, rec.id, rec.name, rec.port, desc, net, known)
        return state, uci, ruleset, net

    async def state(self, router_id: str) -> FirewallState:
        rec = self._record(router_id)
        return (await self._read_on(rec, await self._pool.get(rec)))[0]

    async def ruleset_text(self, router_id: str) -> str:
        rec = self._record(router_id)
        return (await (await self._pool.get(rec)).run(c.NFT_TEXT)).stdout

    def _plan(
        self, rec: RouterRecord, uci: Mapping[str, str], ops: Sequence[UciOp], warnings: Sequence[str]
    ) -> NetPlan:
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="firewall",
            ops=ops,
            current=uci,
            rollback=True,
            warnings=[*warnings, rollback_warning(rec.name, rec.host, "firewall")],
        )

    # ---------------------------------------------------------------- proof by effect
    async def _effect(
        self,
        t: Transport,
        zones: Sequence[tuple[str, Direction, Policy]],
        rules: Sequence[tuple[str, bool]],
        sets: Sequence[tuple[str, bool]] = (),
    ) -> list[NetCheck]:
        """The zone policies, fw4 rules and IP sets as asked in `nft -j list ruleset`, polled for up to
        10 s."""

        def tails(ruleset: Ruleset) -> dict[str, str | None]:
            last: dict[str, str | None] = {}
            for r in ruleset.rules:
                if (r.family, r.table) == ("inet", "fw4"):
                    last[r.chain] = r.jump
            return last

        def holds(ruleset: Ruleset) -> list[NetCheck]:
            last = tails(ruleset)
            comments = {r.comment for r in ruleset.rules}
            out = []
            for zone, direction, policy in zones:
                want = zone_tail(direction, zone, policy)
                got = last.get(f"{direction}_{zone}")
                out.append(
                    NetCheck(
                        f"zone {zone} {direction}",
                        got == want,
                        f"{policy.lower()} in effect"
                        if got == want
                        else f"fw4 ends {direction}_{zone} with {got}",
                    )
                )
            names = {x.name for x in ruleset.sets if (x.family, x.table) == ("inet", "fw4")}
            for name, present in sets:
                there = name in names
                out.append(
                    NetCheck(f"ipset {name}", there == present, "in fw4's ruleset" if there else "gone")
                )
            for name, present in rules:
                there = f"!fw4: {name}" in comments
                detail = (
                    ("in fw4's ruleset" if there else "not in fw4's ruleset")
                    if present
                    else ("still in fw4's ruleset" if there else "gone")
                )
                out.append(NetCheck(f"rule {name}", there == present, detail))
            return out

        checks = holds(parse_ruleset_json((await t.run(c.NFT_JSON)).stdout))
        for _ in range(int(self._settle_s / self._poll_s)):
            if all(ch.ok for ch in checks):
                break
            await self._sleep(self._poll_s)
            checks = holds(parse_ruleset_json((await t.run(c.NFT_JSON)).stdout))
        return checks

    def _verifier(
        self,
        plan: NetPlan,
        uci: Mapping[str, str],
        zones: Sequence[tuple[str, Direction, Policy]],
        rules: Sequence[tuple[str, bool]] = (),
        sets: Sequence[tuple[str, bool]] = (),
    ) -> Callable[[Transport], Awaitable[list[NetCheck]]]:
        async def verify(t: Transport) -> list[NetCheck]:
            effect = await self._effect(t, zones, rules, sets)
            return [*effect, await saved_check(t, c.UCI_FIREWALL, plan.ops, uci)]

        return verify

    # ---------------------------------------------------------------- the filtering model
    def _model_plan(
        self, rec: RouterRecord, state: FirewallState, uci: Mapping[str, str], req: ModelRequest
    ) -> NetPlan:
        ops, warnings = compile_model(req, state, rec.name)
        return self._plan(rec, uci, ops, warnings)

    async def plan_model(self, router_id: str, req: ModelRequest) -> NetPlan:
        rec = self._record(router_id)
        state, uci, _, _ = await self._read_on(rec, await self._pool.get(rec))
        return self._model_plan(rec, state, uci, req)

    async def apply_model(
        self, router_id: str, req: ModelRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            state, uci, _, _ = await self._read_on(rec, t)
            plan = self._model_plan(rec, state, uci, req)
            zones = [(z, d, p) for key, p in req.cells.items() for z, _, d in [key.partition(".")]]
            pins = [
                (PIN_NAMES[op.path.split(".")[1]], op.op == "set")
                for op in plan.ops
                if op.path.count(".") == 1 and op.path.split(".")[1] in PIN_NAMES
            ]
            return Planned(plan, self._verifier(plan, uci, zones, pins), firewall_snapshot(uci))  # type: ignore[arg-type]

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- zones and forwardings
    def _zones_plan(
        self,
        rec: RouterRecord,
        state: FirewallState,
        net: NetworkState,
        uci: Mapping[str, str],
        change: tuple[Sequence[ZoneRequest], Sequence[str], Sequence[ForwardingRequest] | None],
    ) -> NetPlan:
        return self._plan(rec, uci, compile_zones(*change, state, net, rec.name), [])

    async def plan_zones(
        self,
        router_id: str,
        upserts: Sequence[ZoneRequest],
        deletes: Sequence[str],
        forwardings: Sequence[ForwardingRequest] | None,
    ) -> NetPlan:
        rec = self._record(router_id)
        state, uci, _, net = await self._read_on(rec, await self._pool.get(rec))
        return self._zones_plan(rec, state, net, uci, (upserts, deletes, forwardings))

    async def apply_zones(
        self,
        router_id: str,
        upserts: Sequence[ZoneRequest],
        deletes: Sequence[str],
        forwardings: Sequence[ForwardingRequest] | None,
        digest: str | None = None,
    ) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            state, uci, _, net = await self._read_on(rec, t)
            plan = self._zones_plan(rec, state, net, uci, (upserts, deletes, forwardings))
            return Planned(plan, self._verifier(plan, uci, zone_policies(upserts)), firewall_snapshot(uci))

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- rules, port forwards, NAT, IP sets
    async def plan_sections(
        self, router_id: str, kind: Kind, upserts: Sequence[SectionRequest], deletes: Sequence[str]
    ) -> NetPlan:
        rec = self._record(router_id)
        state, uci, _, _ = await self._read_on(rec, await self._pool.get(rec))
        return self._plan(rec, uci, compile_sections(kind, upserts, deletes, state), [])

    async def apply_sections(
        self,
        router_id: str,
        kind: Kind,
        upserts: Sequence[SectionRequest],
        deletes: Sequence[str],
        digest: str | None = None,
    ) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            state, uci, _, _ = await self._read_on(rec, t)
            plan = self._plan(rec, uci, compile_sections(kind, upserts, deletes, state), [])
            rules, sets = expectations(kind, upserts, deletes, state)
            return Planned(plan, self._verifier(plan, uci, [], rules, sets), firewall_snapshot(uci))

        return await self._runner.run_planned(rec, make, digest)
