"""Legacy iptables (v1.0a2 D6): read LuCI's listings; Reset counters and Restart firewall through the plain
apply."""

from __future__ import annotations

from openwrtgui.fw.iptables import (
    PROGRAMS,
    RESET_NOTE,
    RESTART,
    TABLES,
    ZERO,
    IptablesPresence,
    IptablesState,
    IptTable,
    Program,
    listing,
    parse_listing,
)
from openwrtgui.luci_bridge.depends import files_command, parse_ls
from openwrtgui.net.apply import ApplyRunner, NetApplyResult, NetCheck, NetPlan, Planned, net_plan
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Firewall"


def _filter_totals(text: str) -> tuple[int, int]:
    """(bytes counted, rules) in a filter listing: the proof of a reset and of a restart."""
    chains = parse_listing(text)
    counted = sum((c.bytes or 0) + sum(r.bytes for r in c.rules) for c in chains)
    return counted, sum(len(c.rules) for c in chains)


class IptablesService:
    def __init__(self, *, pool: ConnectionPool, routers: RouterStore, runner: ApplyRunner) -> None:
        self._pool = pool
        self._routers = routers
        self._runner = runner

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _presence(self, t: Transport) -> IptablesPresence:
        files = parse_ls((await t.run(files_command(list(PROGRAMS.values())))).stdout)
        return IptablesPresence(
            iptables=files.get(PROGRAMS["iptables"]) == "executable",
            ip6tables=files.get(PROGRAMS["ip6tables"]) == "executable",
        )

    @staticmethod
    def _programs(p: IptablesPresence) -> list[Program]:
        found: list[Program] = []
        if p.iptables:
            found.append("iptables")
        if p.ip6tables:
            found.append("ip6tables")
        return found

    async def presence(self, router_id: str) -> IptablesPresence:
        return await self._presence(await self._pool.get(self._record(router_id)))

    async def state(self, router_id: str) -> IptablesState:
        t = await self._pool.get(self._record(router_id))
        p = await self._presence(t)
        tables: list[IptTable] = []
        for program in self._programs(p):
            for table in TABLES:
                r = await t.run(listing(program, table))
                error = None if r.ok else ((r.stderr or r.stdout).strip() or f"exit {r.exit_status}")
                chains = parse_listing(r.stdout) if r.ok else []
                tables.append(IptTable(program=program, table=table, chains=chains, error=error))
        return IptablesState(iptables=p.iptables, ip6tables=p.ip6tables, tables=tables)

    async def _plan(self, rec: RouterRecord, t: Transport, which: str) -> NetPlan:
        p = await self._presence(t)
        if not p.iptables:
            raise ValueError(f"{rec.name} has no iptables: fw4's rules are under Raw ruleset")
        reset = which == "reset"
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[ZERO[prog] for prog in self._programs(p)] if reset else [RESTART],
            warnings=[RESET_NOTE] if reset else [],
        )

    async def plan_reset(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        return await self._plan(rec, await self._pool.get(rec), "reset")

    async def plan_restart(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        return await self._plan(rec, await self._pool.get(rec), "restart")

    async def _apply(self, router_id: str, which: str, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)
        filter_list = listing("iptables", "filter")

        async def make(t: Transport) -> Planned:
            plan = await self._plan(rec, t, which)
            before = _filter_totals((await t.run(filter_list)).stdout)

            async def verify(t2: Transport) -> list[NetCheck]:
                after = _filter_totals((await t2.run(filter_list)).stdout)
                if which == "reset":
                    ok = before[0] == 0 or after[0] < before[0]
                    return [NetCheck("Counters reset", ok, f"filter: {before[0]} → {after[0]} bytes")]
                return [NetCheck("Rules back", after[1] == before[1], f"filter: {after[1]} rules")]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def apply_reset(self, router_id: str, digest: str | None) -> NetApplyResult:
        return await self._apply(router_id, "reset", digest)

    async def apply_restart(self, router_id: str, digest: str | None) -> NetApplyResult:
        return await self._apply(router_id, "restart", digest)
