"""The Firewall screen: reads, exact previews, applies with the 60 s rollback, proof by effect."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from dataclasses import replace
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
from openwrtgui.fw.custom import CustomRequest, custom_change
from openwrtgui.fw.model import Direction, Policy
from openwrtgui.fw.nft import (
    ChainText,
    Ruleset,
    listing_text,
    parse_ruleset_json,
    table_shape,
    table_texts,
    zone_tail,
)
from openwrtgui.fw.sections import Kind, SectionRequest, compile_sections, expectations
from openwrtgui.fw.state import PIN_DHCP, PIN_SSH, FirewallState, read_firewall
from openwrtgui.fw.tables import TableChange, TableRequest, heredoc, owner_text, table_change
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
from openwrtgui.uci import UciOp, parse_uci_show
from openwrtgui.wifi.service import PreviewChanged

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

    # ---------------------------------------------------------------- other nftables tables
    def _table_change(
        self, state: FirewallState, uci: Mapping[str, str], text: str, req: TableRequest
    ) -> TableChange:
        obj = next((o for o in state.objects if o.key == req.key), None) if req.action != "add" else None
        tables = table_texts(text)
        current = tables.get((obj.family, obj.table)) if obj is not None else None
        included = frozenset(k.split(".")[1] for k, v in uci.items() if k.count(".") == 1 and v == "include")
        return table_change(req, obj, current, included)

    def _table_plans(
        self, rec: RouterRecord, uci: Mapping[str, str], change: TableChange
    ) -> tuple[NetPlan, NetPlan | None]:
        """The runtime change (timer rollback) and, when saved, the include written once it is confirmed. The
        preview shows both, so its digest covers both."""
        runtime = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=(
                heredoc("nft -c -f /dev/stdin", change.script),
                heredoc("nft -f /dev/stdin", change.script),
            ),
            rollback=True,
            backup=change.backup,
            restore=change.restore,
            warnings=[*change.warnings, rollback_warning(rec.name, rec.host, "nftables tables")],
        )
        if not change.include_ops and not change.include_commands:
            return runtime, None
        include = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="firewall",
            ops=change.include_ops,
            current=uci,
            commands=change.include_commands,
        )
        return replace(runtime, lines=(*runtime.lines, *include.lines)), include

    async def plan_table(self, router_id: str, req: TableRequest) -> NetPlan:
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        state, uci, _, _ = await self._read_on(rec, t)
        change = self._table_change(state, uci, (await t.run(c.NFT_TEXT)).stdout, req)
        return self._table_plans(rec, uci, change)[0]

    def _table_check(self, change: TableChange) -> Callable[[Transport], Awaitable[list[NetCheck]]]:
        async def verify(t: Transport) -> list[NetCheck]:
            name = f"table {change.key}"
            if isinstance(change.expect, ChainText):
                listed = await t.run(change.listing)
                got = table_texts(listed.stdout).get(("inet", "fw4"))
                chain = next((x for x in got.chains if x.name == change.expect.name), None) if got else None
                ok = chain is not None and len(chain.rules) == len(change.expect.rules)
                return [NetCheck(name, ok, "the chain holds the asked rules" if ok else "the chain differs")]
            family, table = change.key.split(" ", 1)
            listed = await t.run(f"nft list table {family} {table}")
            if change.expect is None:
                return [NetCheck(name, not listed.ok, "gone" if not listed.ok else "still there")]
            got_table = table_texts(listed.stdout).get((family, table))
            ok = got_table is not None and table_shape(got_table) == table_shape(change.expect)
            return [NetCheck(name, ok, "as asked" if ok else "the table differs")]

        return verify

    async def apply_table(
        self, router_id: str, req: TableRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec = self._record(router_id)
        found: dict[str, Any] = {}

        async def make(t: Transport) -> Planned:
            state, uci, _, _ = await self._read_on(rec, t)
            change = self._table_change(state, uci, (await t.run(c.NFT_TEXT)).stdout, req)
            plan, include = self._table_plans(rec, uci, change)
            if digest is not None and digest != plan.digest:
                raise PreviewChanged(rec.name)
            obj = next((o for o in state.objects if o.key == req.key), None)
            if obj is not None and obj.owner != "app":  # the override, before the change runs
                self._audit.record(
                    router=rec.id,
                    screen=SCREEN,
                    command=f"override {obj.key} (owner {owner_text(obj)})",
                    exit_status=None,
                    source="user",
                )
            found.update(change=change, include=include)
            before = await t.run(change.listing)
            snapshot = Snapshot(change.listing, {"text": before.stdout.strip()}, parse=_text)
            return Planned(plan, self._table_check(change), snapshot)

        first = await self._runner.run_planned(rec, make, digest)
        include: NetPlan | None = found.get("include")
        if not first.applied or include is None:
            return first
        change: TableChange = found["change"]

        async def make_include(t: Transport) -> Planned:
            uci = parse_uci_show((await t.run(c.UCI_FIREWALL)).stdout)
            plan = self._table_plans(rec, uci, change)[1]
            assert plan is not None

            async def verify(t2: Transport) -> list[NetCheck]:
                checks = [await saved_check(t2, c.UCI_FIREWALL, plan.ops, uci)]
                if change.include_file is not None:
                    path, content = change.include_file
                    shown = await t2.run(f"cat {path}")
                    ok = shown.ok and shown.stdout.rstrip("\n") == content
                    checks.append(NetCheck(f"file {path}", ok, "saved" if ok else "differs"))
                return checks

            return Planned(plan, verify)

        second = await self._runner.run_planned(rec, make_include, None)
        error = first.error
        if not second.applied or second.error:  # the uci part may be saved while the file is not
            error = f"Applied at runtime; saving it as an fw4 include failed: {second.error}"
        return NetApplyResult(
            rec.id,
            True,
            first.verified and second.verified,
            (*first.checks, *second.checks),
            error,
            first.host,
        )

    # ---------------------------------------------------------------- custom rule files
    def _custom_plan(self, rec: RouterRecord, state: FirewallState, req: CustomRequest) -> NetPlan:
        if not state.available:
            raise ValueError(state.reason or "fw4 is not running")
        backup, restore, commands = custom_change(req, state.custom)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=commands,
            rollback=True,
            backup=backup,
            restore=restore,
            warnings=[rollback_warning(rec.name, rec.host, "rules files")],
        )

    async def plan_custom(self, router_id: str, req: CustomRequest) -> NetPlan:
        rec = self._record(router_id)
        state = (await self._read_on(rec, await self._pool.get(rec)))[0]
        return self._custom_plan(rec, state, req)

    async def apply_custom(
        self, router_id: str, req: CustomRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec = self._record(router_id)
        path = f"/etc/nftables.d/{req.name}.nft"

        async def verify(t: Transport) -> list[NetCheck]:
            shown = await t.run(f"cat {path}")
            if req.content is None:
                file = NetCheck(f"file {path}", not shown.ok, "gone" if not shown.ok else "still there")
            else:
                same = shown.ok and shown.stdout.rstrip("\n") == req.content.rstrip("\n")
                file = NetCheck(f"file {path}", same, "holds the rules" if same else "differs")
            printed = await t.run(c.FW4_PRINT)
            fw4 = NetCheck(
                "fw4",
                printed.ok,
                "fw4 renders its ruleset with the file" if printed.ok else printed.stderr.strip(),
            )
            return [file, fw4]

        async def make(t: Transport) -> Planned:
            state = (await self._read_on(rec, t))[0]
            before = await t.run(c.CUSTOM_FILES)
            snapshot = Snapshot(c.CUSTOM_FILES, {"text": before.stdout.strip()}, parse=_text)
            return Planned(self._custom_plan(rec, state, req), verify, snapshot)

        return await self._runner.run_planned(rec, make, digest)


def _text(text: str) -> dict[str, str]:
    """A table's listing for the restore check: a live table's counters move meanwhile."""
    return {"text": listing_text(text)}
