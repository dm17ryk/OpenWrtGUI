"""Legacy iptables (v1.0a2 D6): read LuCI's listings; Reset counters and Restart firewall through the plain
apply."""

from __future__ import annotations

from openwrtgui.fw.iptables import (
    IPT_STATE,
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
    reset_proven,
    skipped_lines,
    split_state,
)
from openwrtgui.luci_bridge.depends import files_command, parse_ls
from openwrtgui.net.apply import ApplyRunner, NetApplyResult, NetCheck, NetPlan, Planned, net_plan
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Firewall"


def _filter_totals(text: str) -> tuple[int, int]:
    """(bytes counted, rules) in a filter listing: the proof of a reset and of a restart."""
    chains = parse_listing(text)
    counted = sum((c.bytes or 0) + sum(r.bytes for r in c.rules) for c in chains)
    return counted, sum(len(c.rules) for c in chains)


def _reset_check(program: Program, before: str, after: str) -> NetCheck:
    name = "Counters reset" if program == "iptables" else "IPv6 counters reset"
    was, now = _filter_totals(before)[0], _filter_totals(after)[0]
    return NetCheck(name, reset_proven(before, after), f"filter: {was} → {now} bytes")


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
        """One command for every table, every 10 s while the tab is open (v1.0c Task 3, #63)."""
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        done = await t.run(IPT_STATE)
        p, sections, seen = split_state(done.stdout)
        if seen != frozenset(PROGRAMS):  # empty or cut off: say so, never "no iptables" (#77 minor 6)
            raise TransportError(f"The iptables read of {rec.name} did not answer")
        tables: list[IptTable] = []
        for program in self._programs(p):
            for table in TABLES:
                status, text = sections.get((program, table), (1, ""))
                error = None if status == 0 else (text.strip() or done.stderr.strip() or f"exit {status}")
                chains = parse_listing(text) if status == 0 else []
                skipped = skipped_lines(text) if status == 0 else 0
                tables.append(
                    IptTable(program=program, table=table, chains=chains, error=error, skipped=skipped)
                )
        return IptablesState(iptables=p.iptables, ip6tables=p.ip6tables, tables=tables)

    async def _plan(
        self, rec: RouterRecord, t: Transport, which: str, p: IptablesPresence | None = None
    ) -> NetPlan:
        p = p or await self._presence(t)
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

        async def make(t: Transport) -> Planned:
            p = await self._presence(t)
            plan = await self._plan(rec, t, which, p)
            programs = self._programs(p)
            before = {prog: (await t.run(listing(prog, "filter"))).stdout for prog in programs}

            async def verify(t2: Transport) -> list[NetCheck]:
                after = {prog: (await t2.run(listing(prog, "filter"))).stdout for prog in programs}
                if which == "reset":  # proven per program: ip6tables too (v1.0b2 D4)
                    return [_reset_check(prog, before[prog], after[prog]) for prog in programs]
                rules = _filter_totals(after["iptables"])[1]
                ok = rules == _filter_totals(before["iptables"])[1]
                return [NetCheck("Rules back", ok, f"filter: {rules} rules")]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def apply_reset(self, router_id: str, digest: str | None) -> NetApplyResult:
        return await self._apply(router_id, "reset", digest)

    async def apply_restart(self, router_id: str, digest: str | None) -> NetApplyResult:
        return await self._apply(router_id, "restart", digest)
