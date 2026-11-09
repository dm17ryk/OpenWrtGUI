"""The Faults screen: targets, what the router can do, faults armed (read back from /tmp/owg, so they are
listed after an app or PC restart), arming with proof by effect, holding by a router-side timer, clearing."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from openwrtgui.faults import commands as fc
from openwrtgui.faults.compile import TABLE, CompiledFault, compile_fault, fault_id
from openwrtgui.faults.model import ArmedFault, FaultCaps, FaultRequest, FaultTarget
from openwrtgui.faults.parse import parse_conntrack, rtp_ports
from openwrtgui.faults.targets import read_targets, resolve, router_macs
from openwrtgui.fw.nft import parse_ruleset_json
from openwrtgui.fw.owners import APP_IFB, APP_ROOT
from openwrtgui.fw.tables import heredoc
from openwrtgui.fw.tc import Qdisc, parse_netem, parse_qdiscs, u32_match
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net import commands as pc
from openwrtgui.net.apply import ApplyRunner, NetApplyResult, NetCheck, NetPlan, Planned, net_plan
from openwrtgui.net.state import NetworkState, read_network
from openwrtgui.ports.parse import parse_arl, parse_swconfig_show
from openwrtgui.ports.state import PortsState, read_ports
from openwrtgui.probe.commands import FAULT_RECORDS
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import SettingsStore
from openwrtgui.timer import alive_command, arm_command, cancel_command
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import shell_quote

SCREEN = "Faults"
SETTLE_S = 20.0  # "Link up: polled for up to 20 s"
POLL_S = 1.0
RECORD_DIR = "/tmp/owg"
NOT_ON_AIR = "{router} has no SSID on air"
NO_SWITCH = "This router's switch is not managed by swconfig"
NO_FAMILY = "This router's nftables cannot filter bridged traffic (needs kmod-nft-netdev or kmod-nft-bridge)"


@dataclass(frozen=True)
class WifiIf:
    ifname: str
    ssid: str
    up: bool


@dataclass(frozen=True)
class FaultsState:
    router_id: str
    targets: tuple[FaultTarget, ...]
    armed: tuple[ArmedFault, ...]
    caps: FaultCaps
    unavailable: dict[str, str]
    wifi: tuple[WifiIf, ...]
    ports: PortsState | None


def record_command(fid: str, req: FaultRequest, c: CompiledFault, target: FaultTarget) -> str:
    """The fault's record; `armed_at` is the router's clock, so the command is the same at preview and
    apply."""
    record = {
        "id": fid,
        "kind": req.kind,
        "summary": c.summary,
        "target": asdict(target),
        "device": c.device,
        "clear": list(c.clear),
        "hold_s": c.hold_s,
    }
    head = json.dumps(record, separators=(",", ":"))[:-1] + ","
    return (
        f'printf \'%s"armed_at":%s}}\\n\' {shell_quote(head)} "$(date +%s)" > {RECORD_DIR}/fault-{fid}.json'
    )


def _wifi(status: dict[str, Any]) -> list[WifiIf]:
    out = []
    for radio in status.values():
        if isinstance(radio, dict):
            for iface in radio.get("interfaces", []):
                if isinstance(iface, dict) and iface.get("ifname"):
                    ssid = str(iface.get("config", {}).get("ssid", ""))
                    out.append(WifiIf(str(iface["ifname"]), ssid, bool(radio.get("up"))))
    return out


_DELETE_CHAIN = re.compile(rf"delete chain \S+ {TABLE} (\S+)")
_DELETE_ROOT = re.compile(r"tc qdisc del dev (\S+) root")
_DELETE_INGRESS = re.compile(r"tc qdisc del dev (\S+) ingress")
_PORT_ON = re.compile(r"swconfig dev (\S+) port (\d+) set enable 1")
_AP_ON = re.compile(r"hostapd_cli -i (\S+) enable")
_UNBAN = re.compile(r"ubus call hostapd\.(\S+) del_client '(\{.*\})'")


def clear_line(clear: Sequence[str]) -> str:
    """One fault's clear lines as one command joined by `;`: a part already gone (the table deleted
    elsewhere, a half-armed netem) must not stop the rest. Whether the fault is gone is then checked by
    effect (`_gone_check`); only then is its record removed, so a fault that is still there stays listed."""
    return "; ".join([*clear, "true"])


def record_line(fid: str) -> str:
    return f"rm -f {RECORD_DIR}/fault-{fid}.*"


def caps_from(family: str | None, tc_tables: str, modules: str, tools: str) -> FaultCaps:
    """What a router can do for faults, from its reads: `modules` lists the module files and the kernel's
    built-ins (paths), `tools` one path per tool found."""
    names = {word.rsplit("/", 1)[-1] for word in modules.split()}
    band: Literal["prio", "ets"] | None = (
        "prio" if "sch_prio.ko" in names else "ets" if "sch_ets.ko" in names else None
    )
    return FaultCaps(
        family,  # type: ignore[arg-type]
        frozenset(n.removesuffix(".dist") for n in tc_tables.split()),
        "ifb.ko" in names,
        any(line.endswith("/conntrack") for line in tools.split()),
        band,
        "sch_netem.ko" in names,
    )


class FaultsService:
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
        clock: Callable[[], datetime] = datetime.now,
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
        self._clock = clock
        self._sleep = sleep
        self._settle_s = settle_s
        self._poll_s = poll_s
        self._caps: dict[str, FaultCaps] = {}

    # ---------------------------------------------------------------- reading
    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _caps_for(self, rec: RouterRecord, t: Transport) -> FaultCaps:
        """What the router can do, read once per router."""
        if rec.id not in self._caps:
            family = None
            for name, check in fc.FAMILY_CHECKS.items():
                if (await t.run(check)).ok:
                    family = name
                    break
            tables = await t.run(fc.TC_TABLES)
            modules = (await t.run(fc.MODULES)).stdout
            tools = (await t.run(fc.TOOLS)).stdout
            self._caps[rec.id] = caps_from(family, tables.stdout if tables.ok else "", modules, tools)
        return self._caps[rec.id]

    async def _armed(self, t: Transport) -> list[ArmedFault]:
        records = await t.run(FAULT_RECORDS)
        if not records.ok or not records.stdout.strip():
            return []
        now_router = int((await t.run("date +%s")).stdout.strip() or 0)
        now = self._clock()
        out = []
        for line in records.stdout.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            armed_at = now - timedelta(seconds=now_router - int(r.get("armed_at", now_router)))
            hold = r.get("hold_s")
            until = armed_at + timedelta(seconds=int(hold)) if hold else None
            target = FaultTarget(
                **{k: r.get("target", {}).get(k) for k in ("name", "mac", "ip", "via", "device")}
            )
            out.append(
                ArmedFault(
                    r["id"],
                    r["kind"],
                    r.get("summary", ""),
                    target,
                    r.get("device"),
                    tuple(r.get("clear", [])),
                    armed_at,
                    until,
                )
            )
        return sorted(out, key=lambda a: a.armed_at)

    async def _read_on(
        self, rec: RouterRecord, t: Transport
    ) -> tuple[FaultsState, NetworkState, list[Qdisc]]:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        net, uci = await read_network(t, rec.id, desc)
        ports = await read_ports(t, rec, desc, net, uci)
        caps = await self._caps_for(rec, t)
        wifi = _wifi(await ubus_call(t, "network.wireless", "status") or {})
        targets = await read_targets(t, net, self._settings.load().known_devices)
        qdiscs = parse_qdiscs((await t.run("tc qdisc show")).stdout)
        unavailable: dict[str, str] = {}
        if caps.family is None:
            unavailable |= {"isolate": NO_FAMILY, "block": NO_FAMILY}
        if not ports.managed:
            unavailable["link_down"] = NO_SWITCH
        if not caps.netem:
            unavailable["netem"] = f"{rec.name} has no netem (sch_netem)"
        if not any(w.up for w in wifi):
            text = NOT_ON_AIR.format(router=rec.name)
            unavailable |= {"deauth": text, "ban": text, "ap_down": text}
        state = FaultsState(
            rec.id,
            tuple(targets),
            tuple(await self._armed(t)),
            caps,
            unavailable,
            tuple(wifi),
            ports if ports.managed else None,
        )
        return state, net, qdiscs

    async def state(self, router_id: str) -> FaultsState:
        rec = self._record(router_id)
        return (await self._read_on(rec, await self._pool.get(rec)))[0]

    # ---------------------------------------------------------------- arming
    async def _compile(
        self, rec: RouterRecord, t: Transport, req: FaultRequest
    ) -> tuple[NetPlan, CompiledFault, str, FaultTarget, FaultsState]:
        state, net, qdiscs = await self._read_on(rec, t)
        if req.kind in state.unavailable:
            raise ValueError(state.unavailable[req.kind])
        needs = "mac" if req.kind in ("isolate", "link_down", "deauth", "ban", "ap_down") else "ip"
        target = resolve(req.target, state.targets, net, rec.name, needs, await router_macs(t))  # type: ignore[arg-type]
        if req.kind == "link_down" and req.port is None and state.ports and state.ports.switch and target.mac:
            arl = parse_arl((await t.run(pc.swconfig_arl(state.ports.switch))).stdout)
            if target.mac in arl:
                req = replace(req, port=arl[target.mac])
        rtp: tuple[int, ...] = ()
        if req.kind == "block" and req.flow in ("rtp_in", "rtp_out") and target.ip:
            rtp = rtp_ports(parse_conntrack((await t.run(fc.CONNTRACK_UDP)).stdout), target.ip)
        fid = fault_id(req, [a.id for a in state.armed])
        c = compile_fault(req, target, state.caps, state.ports, qdiscs, state.armed, rtp, rec.name, id=fid)
        commands = [f"mkdir -p {RECORD_DIR}"]
        if c.nft:
            commands.append(heredoc("nft -f /dev/stdin", "\n".join(c.nft)))
        commands += c.commands
        if c.record:
            commands.append(record_command(fid, req, c, target))
            if c.hold_s:
                lines = c.clear if c.timer is None else c.timer
                commands.append(arm_command(f"fault-{fid}", c.hold_s, list(lines)))
        plan = net_plan(router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=commands)
        return plan, c, fid, target, state

    async def plan_fault(self, router_id: str, req: FaultRequest) -> NetPlan:
        rec = self._record(router_id)
        return (await self._compile(rec, await self._pool.get(rec), req))[0]

    async def apply_fault(
        self, router_id: str, req: FaultRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec = self._record(router_id)
        found: dict[str, Any] = {}

        async def make(t: Transport) -> Planned:
            plan, c, fid, target, state = await self._compile(rec, t, req)
            found.update(c=c, fid=fid, family=state.caps.family)

            async def verify(t2: Transport) -> list[NetCheck]:
                return await self._checks(t2, state, c, fid, target)

            return Planned(plan, verify)

        result = await self._runner.run_planned(rec, make, digest)
        if result.verified or not result.applied or not found or not found["c"].clear:
            return result
        # Part of the fault ran but no record says so (a later command failed): nothing on the screen could
        # clear it, so it is removed now, like a refused change is undone.
        fid: str = found["fid"]
        t = await self._pool.get(rec)
        if (await t.run(f"cat {RECORD_DIR}/fault-{fid}.json")).ok:
            return result
        undo = await self._remove(rec, [(fid, tuple(found["c"].clear))], found["family"])
        note = (
            "The app removed the parts that had run."
            if undo.verified
            else f"Removing them failed: {undo.error}"
        )
        return replace(result, checks=(*result.checks, *undo.checks), error=f"{result.error}. {note}")

    async def _remove(
        self, rec: RouterRecord, faults: Sequence[tuple[str, tuple[str, ...]]], family: str | None
    ) -> NetApplyResult:
        """Run the clear lines of faults that have no record, whatever is still there (see `clear_line`)."""

        async def make(t: Transport) -> Planned:
            commands = [clear_line(clear) for _, clear in faults]
            plan = net_plan(
                router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=commands
            )

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await self._gone_check(t2, fid, clear, family) for fid, clear in faults]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, None, guarded=False)

    async def _gone_check(self, t: Transport, fid: str, clear: Sequence[str], family: str | None) -> NetCheck:
        """A cleared fault by effect: its chains, qdiscs, ifb, switch port, AP and ban are gone."""
        left: list[str] = []
        chains = [m.group(1) for line in clear if (m := _DELETE_CHAIN.search(line))]
        if chains and family is not None:
            listed = await t.run(f"nft -j list table {family} {TABLE}")
            have = {ch.name for ch in parse_ruleset_json(listed.stdout).chains} if listed.ok else set()
            left += [f"chain {name}" for name in chains if name in have]
        qdiscs = parse_qdiscs((await t.run("tc qdisc show")).stdout)
        for line in clear:
            left += await self._left_by(t, line, qdiscs)
        return NetCheck(
            f"cleared {fid}", not left, "nothing left" if not left else f"left: {', '.join(left)}"
        )

    async def _left_by(self, t: Transport, line: str, qdiscs: Sequence[Qdisc]) -> list[str]:
        """What one clear line should have undone and is still there."""
        if (m := _DELETE_ROOT.fullmatch(line)) and any(
            q.dev == m.group(1) and q.root and q.handle == APP_ROOT for q in qdiscs
        ):
            return [f"netem on {m.group(1)}"]
        if (m := _DELETE_INGRESS.fullmatch(line)) and any(
            q.dev == m.group(1) and q.kind == "ingress" for q in qdiscs
        ):
            return [f"ingress on {m.group(1)}"]
        if line == f"ip link del {APP_IFB}" and any(q.dev == APP_IFB for q in qdiscs):
            return [APP_IFB]
        if m := _PORT_ON.fullmatch(line):
            live = parse_swconfig_show(m.group(1), (await t.run(pc.swconfig_show(m.group(1)))).stdout)
            if any(p.num == int(m.group(2)) and p.enabled is False for p in live.ports):
                return [f"port {m.group(2)} off"]
        if (m := _AP_ON.fullmatch(line)) and "state=DISABLED" in (
            await t.run(f"hostapd_cli -i {m.group(1)} status")
        ).stdout:
            return [f"{m.group(1)} down"]
        if m := _UNBAN.fullmatch(line):
            mac = str(json.loads(m.group(2)).get("addr", "")).lower()
            bans = await ubus_call(t, f"hostapd.{m.group(1)}", "list_bans")
            if mac and mac in json.dumps(bans or {}).lower():
                return [f"ban on {mac}"]
        return []

    # ---------------------------------------------------------------- proof by effect
    async def _checks(
        self, t: Transport, state: FaultsState, c: CompiledFault, fid: str, target: FaultTarget
    ) -> list[NetCheck]:
        checks: list[NetCheck] = []
        if c.nft:
            checks.append(await self._nft_check(t, state.caps, c, fid))
        for command in c.commands:
            if command.startswith("tc qdisc add dev") and " netem " in command:
                checks.append(await self._netem_check(t, c, target))
                break
        if any("swconfig" in x for x in c.commands):
            checks.append(await self._port_check(t, state, c))
        if c.commands and "del_client" in c.commands[0] and target.via:
            checks.append(await self._client_check(t, target, banned=c.record))
        if c.commands and c.commands[0].startswith("hostapd_cli") and target.via:
            shown = await t.run(f"hostapd_cli -i {target.via} status")
            down = "state=DISABLED" in shown.stdout
            checks.append(
                NetCheck(f"ap down {target.via}", down, "hostapd stopped the BSS" if down else "still on air")
            )
        if c.record:
            if c.hold_s:
                alive = (await t.run(alive_command(f"fault-{fid}"))).ok
                checks.append(
                    NetCheck("timer", alive, f"clears in {c.hold_s} s" if alive else "no timer runs")
                )
            there = (await t.run(f"cat {RECORD_DIR}/fault-{fid}.json")).ok
            checks.append(NetCheck("record", there, "kept on the router" if there else "missing"))
        return checks

    async def _nft_check(self, t: Transport, caps: FaultCaps, c: CompiledFault, fid: str) -> NetCheck:
        listed = parse_ruleset_json((await t.run(f"nft -j list table {caps.family} {TABLE}")).stdout)
        hooks = {"egress", "ingress"} if caps.family == "netdev" else {"postrouting", "prerouting"}
        chains = {ch.name: ch for ch in listed.chains}
        ok = all(name in chains and chains[name].hook in hooks for name in c.chains)
        rules = [r for r in listed.rules if r.chain in c.chains]
        ok = ok and bool(rules) and all(r.packets is not None for r in rules)
        detail = (
            "in place before fw4's ct state established accept, counters readable"
            if ok
            else "not in place as asked"
        )
        return NetCheck(f"fault {fid}", ok, detail)

    async def _netem_check(self, t: Transport, c: CompiledFault, target: FaultTarget) -> NetCheck:
        dev = c.device or ""
        want = " ".join(c.commands)
        ok = True
        # the whole listing: filtered by device, iproute2 leaves out `dev X` (AP2, 2026-11-07)
        qdiscs = parse_qdiscs((await t.run("tc qdisc show")).stdout)
        if f"dev {dev} root handle {APP_ROOT}" in want:
            q = [x for x in qdiscs if x.dev == dev and x.handle == "1ee8:"]
            shown = (await t.run(f"tc filter show dev {dev} parent {APP_ROOT}")).stdout
            ok = bool(q) and bool(parse_netem(q[0].params)) and u32_match(target.ip or "", "dst") in shown
        if APP_IFB in want:
            q = [x for x in qdiscs if x.dev == APP_IFB and x.handle == "1ee9:"]
            shown = (await t.run(f"tc filter show dev {dev} parent ffff:")).stdout
            ok = ok and bool(q) and u32_match(target.ip or "", "src") in shown
        return NetCheck(
            f"netem {dev}", ok, "netem on the target's traffic only" if ok else "not in place as asked"
        )

    async def _port_check(self, t: Transport, state: FaultsState, c: CompiledFault) -> NetCheck:
        assert state.ports is not None and state.ports.switch is not None
        port = int(c.commands[0].split()[4])
        label = next((p.label for p in state.ports.ports if p.num == port), f"port {port}")
        for attempt in range(int(self._settle_s / self._poll_s) + 1):
            if attempt:
                await self._sleep(self._poll_s)
            live = parse_swconfig_show(
                state.ports.switch, (await t.run(pc.swconfig_show(state.ports.switch))).stdout
            )
            p = next((x for x in live.ports if x.num == port), None)
            if p is not None and p.enabled is False and not p.link:
                return NetCheck(f"port {label}", True, "off, no link")
        return NetCheck(f"port {label}", False, f"not off with the link down after {self._settle_s:g} s")

    async def _client_check(self, t: Transport, target: FaultTarget, *, banned: bool) -> NetCheck:
        ifname, mac = target.via or "", (target.mac or "").lower()
        if banned:
            listed = await ubus_call(t, f"hostapd.{ifname}", "list_bans")
            ok = mac in json.dumps(listed or {}).lower()
            return NetCheck(
                "ban",
                ok if ok else None,
                f"{mac} banned" if ok else "hostapd took the request; not read back",
            )
        for attempt in range(3):
            if attempt:
                await self._sleep(1.0)
            clients = (await ubus_call(t, f"hostapd.{ifname}", "get_clients") or {}).get("clients", {})
            flags = {k.lower(): v for k, v in clients.items()}.get(mac)
            # hostapd lists a deauthenticated station, no longer associated, for about a second, and a phone
            # may join again by the next look (AP2, 2026-11-09); without the flag it counts as associated
            if flags is None or (isinstance(flags, dict) and flags.get("assoc", True) is False):
                return NetCheck("deauth", True, f"{mac} left {ifname}")
        return NetCheck("deauth", None, "still listed or re-joined")

    # ---------------------------------------------------------------- clearing
    async def _clear_plan(
        self, rec: RouterRecord, t: Transport, ids: Sequence[str] | None
    ) -> tuple[NetPlan, list[ArmedFault], FaultsState]:
        state, _, qdiscs = await self._read_on(rec, t)
        chosen = [a for a in state.armed if ids is None or a.id in ids]
        if ids is not None and len(chosen) != len(set(ids)):
            raise ValueError("A fault to clear is no longer armed")
        commands = [cancel_command(f"fault-{a.id}") for a in chosen if a.until is not None]
        family = state.caps.family
        # the whole table first: a fault's own clear deletes the table when it is the last one there
        if ids is None and family is not None and (await t.run(f"nft list table {family} {TABLE}")).ok:
            commands.append(f"nft delete table {family} {TABLE}")
        commands += [clear_line(a.clear) for a in chosen if a.clear]
        if (
            ids is None
            and any(q.dev == APP_IFB for q in qdiscs)
            and not any(f"ip link del {APP_IFB}" in c for c in commands)
        ):
            commands.append(f"ip link del {APP_IFB}")
        if not commands:
            raise ValueError("Nothing is armed on this router.")
        plan = net_plan(router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=commands)
        return plan, chosen, state

    async def plan_clear(self, router_id: str, ids: Sequence[str] | None) -> NetPlan:
        rec = self._record(router_id)
        return (await self._clear_plan(rec, await self._pool.get(rec), ids))[0]

    async def apply_clear(
        self, router_id: str, ids: Sequence[str] | None, digest: str | None = None
    ) -> NetApplyResult:
        """Allowed while Bench Guard is live: it only removes what this app armed, and a fault left in place
        disturbs a run more (scope note, v0.4 plan)."""
        rec = self._record(router_id)
        found: dict[str, list[ArmedFault]] = {}

        async def make(t: Transport) -> Planned:
            plan, chosen, state = await self._clear_plan(rec, t, ids)
            found["chosen"] = chosen

            async def verify(t2: Transport) -> list[NetCheck]:
                checks = [await self._gone_check(t2, a.id, a.clear, state.caps.family) for a in chosen]
                if ids is None and state.caps.family is not None:
                    gone = not (await t2.run(f"nft list table {state.caps.family} {TABLE}")).ok
                    checks.append(NetCheck(f"table {TABLE}", gone, "gone" if gone else "still there"))
                return checks

            return Planned(plan, verify)

        result = await self._runner.run_planned(rec, make, digest, guarded=False)
        result = await self._drop_records(rec, result, found.get("chosen", []))
        live = self._guard.state()
        if live.live and result.applied:
            run = live.reasons[0].text if live.reasons else "a harness run"
            result = replace(result, error=f"Cleared although Bench Guard is live ({run})")
        return result

    async def _drop_records(
        self, rec: RouterRecord, result: NetApplyResult, chosen: Sequence[ArmedFault]
    ) -> NetApplyResult:
        """Remove the record of each fault seen gone; one still there keeps its record and stays listed."""
        checks = {c.name: c for c in result.checks}
        gone = [a for a in chosen if (c := checks.get(f"cleared {a.id}")) is not None and c.ok]
        if gone:

            async def make(t: Transport) -> Planned:
                commands = [record_line(a.id) for a in gone]
                plan = net_plan(
                    router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=commands
                )

                async def verify(t2: Transport) -> list[NetCheck]:
                    out = []
                    for a in gone:
                        left = (await t2.run(f"cat {RECORD_DIR}/fault-{a.id}.json")).ok
                        out.append(NetCheck(f"record {a.id}", not left, "still there" if left else "removed"))
                    return out

                return Planned(plan, verify)

            dropped = await self._runner.run_planned(rec, make, None, guarded=False)
            result = replace(
                result,
                verified=result.verified and dropped.verified,
                checks=(*result.checks, *dropped.checks),
                error=result.error or dropped.error,
            )
        kept = [
            f"{a.summary} is not cleared ({c.detail}); it stays listed to clear again"
            for a in chosen
            if (c := checks.get(f"cleared {a.id}")) is not None and c.ok is False
        ]
        if kept:
            result = replace(result, error="; ".join([*([result.error] if result.error else []), *kept]))
        return result
