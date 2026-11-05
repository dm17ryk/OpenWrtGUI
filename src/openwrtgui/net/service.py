"""The Network & DHCP screen: reads, exact previews, applies (plain or with rollback), proof by effect."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any

from openwrtgui.forms import OptionRow
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import ApplyRunner, NetApplyResult, NetCheck, NetPlan, net_plan, rollback_warning
from openwrtgui.net.interfaces import (
    InterfaceRequest,
    compile_interface,
    interface_rows,
    pc_warning,
    target_host,
)
from openwrtgui.net.model import Address, parse_cidr
from openwrtgui.net.state import NetworkState, protocols, read_network
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged, WifiService

SCREEN = "Network"
SETTLE_S = 20.0  # "Link up: polled for up to 20 s"
POLL_S = 1.0


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
