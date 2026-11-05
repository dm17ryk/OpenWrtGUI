"""The Network & DHCP screen: reads, exact previews, applies (plain or with rollback), proof by effect."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

from openwrtgui.forms import OptionRow
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.access import AccessChange, AccessState, compile_access, read_access
from openwrtgui.net.apply import (
    NOTHING,
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    net_plan,
    rollback_warning,
    saved_check,
    service_check,
)
from openwrtgui.net.commands import UCI_DHCP
from openwrtgui.net.dhcp import (
    DNSMASQ_RELOAD,
    DhcpRequest,
    HostRequest,
    compile_dhcp,
    compile_hosts,
    conflict_warnings,
    reloads_for,
)
from openwrtgui.net.dns import DnsRequest, compile_dns
from openwrtgui.net.interfaces import (
    InterfaceRequest,
    compile_interface,
    interface_rows,
    pc_warning,
    target_host,
)
from openwrtgui.net.model import Address, Lease, parse_cidr
from openwrtgui.net.parse import parse_host_hints, parse_leases
from openwrtgui.net.routes import (
    LiveTables,
    RouteRequest,
    RuleRequest,
    compile_routes,
    expectations,
    read_live,
)
from openwrtgui.net.state import NetworkState, protocols, read_network
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import UciOp, drop_unchanged
from openwrtgui.wifi.service import PreviewChanged, WifiService
from openwrtgui.wifi.state import read_uci

SCREEN = "Network"
SETTLE_S = 20.0  # "Link up: polled for up to 20 s"
POLL_S = 1.0
_ACL = re.compile(r"hostapd_cli -i (\S+) (deny_acl|accept_acl) (ADD_MAC|DEL_MAC) (\S+)")


def as_previewed(rec: RouterRecord, plan: NetPlan, digest: str | None) -> NetPlan:
    """Apply runs only the lines the user saw: a router changed since the preview gives other lines."""
    if digest is not None and digest != plan.digest:
        raise PreviewChanged(rec.name)
    return plan


def network_snapshot(uci: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in uci.items() if k.startswith("network.")}


class NetworkService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        descriptions: MutableMapping[str, SelfDescription],
        statuses: Mapping[str, RouterStatus],
        runner: ApplyRunner,
        wifi: WifiService,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        settle_s: float = SETTLE_S,
        poll_s: float = POLL_S,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._descriptions = descriptions
        self._statuses = statuses
        self._runner = runner
        self._wifi = wifi
        self._sleep = sleep
        self._settle_s = settle_s
        self._poll_s = poll_s

    # ---------------------------------------------------------------- reading
    async def _connect(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec, await self._pool.get(rec)

    async def _description(self, rec: RouterRecord, t: Transport) -> SelfDescription:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        return desc

    async def _read(
        self, router_id: str
    ) -> tuple[RouterRecord, Transport, NetworkState, dict[str, str], SelfDescription]:
        rec, t = await self._connect(router_id)
        desc = await self._description(rec, t)
        state, uci = await read_network(t, rec.id, desc)
        return rec, t, state, uci, desc

    async def state(self, router_id: str) -> NetworkState:
        return (await self._read(router_id))[2]

    # ---------------------------------------------------------------- router addresses
    async def interface_options(self, router_id: str, name: str) -> list[OptionRow]:
        _rec, _t, state, uci, desc = await self._read(router_id)
        return interface_rows(state, uci, protocols(desc), name)

    def _interface_plan(
        self,
        rec: RouterRecord,
        state: NetworkState,
        uci: Mapping[str, str],
        desc: SelfDescription,
        req: InterfaceRequest,
    ) -> NetPlan:
        ops, secrets, warnings = compile_interface(req, state, uci, protocols(desc), rec.name)
        target = target_host(req, state, rec)
        own_address = req.address if req.name == state.own_interface else None
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="network",
            ops=ops,
            current=uci,
            rollback=True,
            target_host=target,
            warnings=[
                *warnings,
                rollback_warning(rec.name, target or rec.host),
                *pc_warning(state, own_address),
            ],
            secrets=secrets,
        )

    async def plan_interface(self, router_id: str, req: InterfaceRequest) -> NetPlan:
        rec, _t, state, uci, desc = await self._read(router_id)
        return self._interface_plan(rec, state, uci, desc, req)

    async def apply_interface(
        self, router_id: str, req: InterfaceRequest, digest: str | None = None
    ) -> NetApplyResult:
        rec, t, state, uci, desc = await self._read(router_id)
        plan = as_previewed(rec, self._interface_plan(rec, state, uci, desc, req), digest)

        async def verify(t2: Transport) -> list[NetCheck]:
            return [await self._interface_check(t2, req, state)]

        return await self._runner.run(rec, t, plan, verify, network_snapshot(uci))

    # ---------------------------------------------------------------- DHCP server and fixed addresses
    def _dhcp_plan(
        self, rec: RouterRecord, state: NetworkState, uci: Mapping[str, str], req: DhcpRequest
    ) -> NetPlan:
        ops = compile_dhcp(req, state, uci)
        current = next((d for d in state.dhcp if d.interface == req.interface), None)
        conf = state.conf(req.interface)
        warnings: list[str] = []
        if req.enabled and not (current and current.enabled) and conf and conf.address:
            warnings = conflict_warnings(rec, conf.address, self._statuses, self._routers)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="dhcp",
            ops=ops,
            current=uci,
            reloads=reloads_for(ops),
            warnings=warnings,
        )

    async def plan_dhcp(self, router_id: str, req: DhcpRequest) -> NetPlan:
        rec, _t, state, uci, _desc = await self._read(router_id)
        return self._dhcp_plan(rec, state, uci, req)

    async def apply_dhcp(self, router_id: str, req: DhcpRequest, digest: str | None = None) -> NetApplyResult:
        rec, t, state, uci, _desc = await self._read(router_id)
        plan = as_previewed(rec, self._dhcp_plan(rec, state, uci, req), digest)
        return await self._runner.run(rec, t, plan, self._dhcp_checks(plan, uci))

    def _hosts_plan(
        self,
        rec: RouterRecord,
        state: NetworkState,
        uci: Mapping[str, str],
        upserts: Sequence[HostRequest],
        deletes: Sequence[str],
    ) -> NetPlan:
        ops, warnings = compile_hosts(upserts, deletes, state, uci, rec.name)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="dhcp",
            ops=ops,
            current=uci,
            reloads=reloads_for(ops),
            warnings=warnings,
        )

    async def plan_hosts(
        self, router_id: str, upserts: Sequence[HostRequest], deletes: Sequence[str]
    ) -> NetPlan:
        rec, _t, state, uci, _desc = await self._read(router_id)
        return self._hosts_plan(rec, state, uci, upserts, deletes)

    async def apply_hosts(
        self,
        router_id: str,
        upserts: Sequence[HostRequest],
        deletes: Sequence[str],
        digest: str | None = None,
    ) -> NetApplyResult:
        rec, t, state, uci, _desc = await self._read(router_id)
        plan = as_previewed(rec, self._hosts_plan(rec, state, uci, upserts, deletes), digest)
        return await self._runner.run(rec, t, plan, self._dhcp_checks(plan, uci))

    def _dhcp_checks(
        self, plan: NetPlan, uci: Mapping[str, str]
    ) -> Callable[[Transport], Awaitable[list[NetCheck]]]:
        async def verify(t: Transport) -> list[NetCheck]:
            return [await saved_check(t, UCI_DHCP, plan.ops, uci), await service_check(t, "dnsmasq")]

        return verify

    async def leases(self, router_id: str) -> list[Lease]:
        _rec, t = await self._connect(router_id)
        leases = parse_leases(await ubus_call(t, "luci-rpc", "getDHCPLeases") or {})
        hints = parse_host_hints(await ubus_call(t, "luci-rpc", "getHostHints") or {})
        return [replace(lease, hostname=lease.hostname or hints.get(lease.mac or "")) for lease in leases]

    # ---------------------------------------------------------------- DNS
    def _dns_plan(
        self, rec: RouterRecord, state: NetworkState, uci: Mapping[str, str], req: DnsRequest
    ) -> NetPlan:
        ops = compile_dns(req, state.dns)
        return net_plan(
            router_id=rec.id, screen=SCREEN, config="dhcp", ops=ops, current=uci, reloads=(DNSMASQ_RELOAD,)
        )

    async def plan_dns(self, router_id: str, req: DnsRequest) -> NetPlan:
        rec, _t, state, uci, _desc = await self._read(router_id)
        return self._dns_plan(rec, state, uci, req)

    async def apply_dns(self, router_id: str, req: DnsRequest, digest: str | None = None) -> NetApplyResult:
        rec, t, state, uci, _desc = await self._read(router_id)
        plan = as_previewed(rec, self._dns_plan(rec, state, uci, req), digest)
        return await self._runner.run(rec, t, plan, self._dhcp_checks(plan, uci))

    # ---------------------------------------------------------------- static routes and rules
    def _routes_plan(
        self,
        rec: RouterRecord,
        state: NetworkState,
        uci: Mapping[str, str],
        change: tuple[Sequence[RouteRequest], Sequence[str], Sequence[RuleRequest], Sequence[str]],
    ) -> NetPlan:
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="network",
            ops=compile_routes(*change, state),
            current=uci,
            rollback=True,
            warnings=[rollback_warning(rec.name, rec.host)],
        )

    async def plan_routes(
        self,
        router_id: str,
        upserts: Sequence[RouteRequest],
        deletes: Sequence[str],
        rule_upserts: Sequence[RuleRequest],
        rule_deletes: Sequence[str],
    ) -> NetPlan:
        rec, _t, state, uci, _desc = await self._read(router_id)
        return self._routes_plan(rec, state, uci, (upserts, deletes, rule_upserts, rule_deletes))

    async def apply_routes(
        self,
        router_id: str,
        upserts: Sequence[RouteRequest],
        deletes: Sequence[str],
        rule_upserts: Sequence[RuleRequest],
        rule_deletes: Sequence[str],
        digest: str | None = None,
    ) -> NetApplyResult:
        rec, t, state, uci, _desc = await self._read(router_id)
        change = (upserts, deletes, rule_upserts, rule_deletes)
        plan = as_previewed(rec, self._routes_plan(rec, state, uci, change), digest)

        async def verify(t2: Transport) -> list[NetCheck]:
            return await self._route_checks(t2, state, *change)

        return await self._runner.run(rec, t, plan, verify, network_snapshot(uci))

    async def live_routes(self, router_id: str) -> LiveTables:
        _rec, t = await self._connect(router_id)
        return await read_live(t)

    async def _route_checks(
        self,
        t: Transport,
        state: NetworkState,
        upserts: Sequence[RouteRequest],
        deletes: Sequence[str],
        rule_upserts: Sequence[RuleRequest],
        rule_deletes: Sequence[str],
    ) -> list[NetCheck]:
        """Each route in the live table (same target, gateway and device) or gone; each rule by priority;
        polled for up to 20 s."""
        want = expectations(state, upserts, deletes, rule_upserts, rule_deletes)
        live = await read_live(t)
        for _ in range(int(self._settle_s / self._poll_s)):
            if live.raw is not None or all(e.holds(live) for e in want):
                break
            await self._sleep(self._poll_s)
            live = await read_live(t)
        if live.raw is not None:
            return [NetCheck(e.name, None, "not checked: this router's ip has no JSON output") for e in want]
        return [
            NetCheck(e.name, e.holds(live), "as asked" if e.holds(live) else "not in the live table as asked")
            for e in want
        ]

    # ---------------------------------------------------------------- Wi-Fi access by MAC
    async def _access_read(
        self, router_id: str
    ) -> tuple[RouterRecord, Transport, AccessState, dict[str, str]]:
        rec, t = await self._connect(router_id)
        uci = await read_uci(t)
        status = await ubus_call(t, "network.wireless", "status") or {}
        hints = parse_host_hints(await ubus_call(t, "luci-rpc", "getHostHints") or {})
        return rec, t, await read_access(t, uci, status, hints), uci

    async def access(self, router_id: str) -> AccessState:
        return (await self._access_read(router_id))[2]

    async def _access_plan(
        self, rec: RouterRecord, state: AccessState, uci: Mapping[str, str], change: AccessChange
    ) -> tuple[NetPlan, dict[str, list[UciOp]]]:
        """Saved changes are Wi-Fi config changes, shown and applied as the Wi-Fi screen does them (reload,
        TX mask, checks); the runtime ones are hostapd commands."""
        ops, commands, warnings = compile_access(change, state, rec.name)
        by_radio: dict[str, list[UciOp]] = {}
        for op in drop_unchanged(ops, uci):
            radio = uci.get(f"wireless.{op.path.split('.')[1]}.device", "")
            by_radio.setdefault(radio, []).append(op)
        lines: list[str] = []
        for radio, radio_ops in by_radio.items():
            wifi_plan = await self._wifi.plan_ops(rec.id, radio, radio_ops)
            lines += wifi_plan.lines
            warnings += wifi_plan.warnings
        if not lines and not commands:
            raise ValueError(NOTHING)
        plan = NetPlan(
            router_id=rec.id,
            screen=SCREEN,
            config="wireless" if by_radio else None,
            lines=(*lines, *commands),
            ops=tuple(op for radio_ops in by_radio.values() for op in radio_ops),
            commands=tuple(commands),
            reloads=(),
            rollback=False,
            target_host=None,
            warnings=tuple(warnings),
            secrets=(),
        )
        return plan, by_radio

    async def plan_access(self, router_id: str, change: AccessChange) -> NetPlan:
        rec, _t, state, uci = await self._access_read(router_id)
        return (await self._access_plan(rec, state, uci, change))[0]

    async def apply_access(
        self, router_id: str, change: AccessChange, digest: str | None = None
    ) -> NetApplyResult:
        rec, t, state, uci = await self._access_read(router_id)
        plan, by_radio = await self._access_plan(rec, state, uci, change)
        as_previewed(rec, plan, digest)
        if not by_radio:
            return await self._runner.run(rec, t, plan, self._runtime_checks(plan))
        checks: list[NetCheck] = []
        applied = verified = True
        errors: list[str] = []
        for radio, radio_ops in by_radio.items():
            done = await self._wifi.apply_ops(rec.id, radio, radio_ops, screen=SCREEN)
            checks += [NetCheck(c.name, c.ok, c.detail) for c in done.checks]
            applied, verified = applied and done.applied, verified and done.verified
            errors += [done.error] if done.error else []
        return NetApplyResult(rec.id, applied, verified, tuple(checks), "; ".join(errors) or None, rec.host)

    def _runtime_checks(self, plan: NetPlan) -> Callable[[Transport], Awaitable[list[NetCheck]]]:
        async def verify(t: Transport) -> list[NetCheck]:
            checks = []
            for command in plan.commands:
                if m := _ACL.fullmatch(command):
                    ifname, kind, verb, mac = m.groups()
                    shown = await t.run(f"hostapd_cli -i {ifname} {kind} SHOW")
                    listed = mac in shown.stdout.lower()
                    want = verb == "ADD_MAC"
                    where = "in" if want else "off"
                    checks.append(NetCheck(f"runtime list {ifname}", listed == want, f"{mac} {where} {kind}"))
            return checks or [NetCheck("hostapd", True, "hostapd took the request")]

        return verify

    async def _interface_check(self, t: Transport, req: InterfaceRequest, state: NetworkState) -> NetCheck:
        """The interface as asked, polled for up to 20 s: gone, there (no address), or up with its address."""
        name = f"interface {req.name}"
        conf = state.conf(req.name)
        proto = req.proto or (conf.proto if conf else "none")
        want: Address | None = None
        if proto == "static":
            want = parse_cidr(req.address) if req.address else (conf.address if conf else None)
        last: dict[str, Any] | None = None
        for attempt in range(int(self._settle_s / self._poll_s) + 1):
            if attempt:
                await self._sleep(self._poll_s)
            last = await ubus_call(t, f"network.interface.{req.name}", "status")
            if req.delete:
                if last is None:
                    return NetCheck(name, True, f"{req.name} is gone")
                continue
            if last is None:
                continue
            if proto == "none":
                return NetCheck(name, True, f"{req.name} is there, with no address")
            ipv4 = [Address(str(a["address"]), int(a["mask"])) for a in last.get("ipv4-address", [])]
            if last.get("up") and (want is None or want in ipv4):
                return NetCheck(name, True, f"up with {want}" if want else "up")
        if req.delete:
            return NetCheck(name, False, f"{req.name} is still there after {self._settle_s:g} s")
        if last is None:
            return NetCheck(name, False, f"the router does not know {req.name}")
        if want is not None:
            return NetCheck(name, False, f"not up with {want} after {self._settle_s:g} s")
        return NetCheck(name, None, f"not up after {self._settle_s:g} s (waiting for a link or a lease)")
