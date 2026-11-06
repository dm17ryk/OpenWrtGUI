"""Network & DHCP per router: state, exact previews and applies (plain or with rollback), leases, routes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.wifi_api import OptionEditIn
from openwrtgui.context import AppContext
from openwrtgui.forms import OptionEdit, OptionRow
from openwrtgui.net.access import AccessChange, AccessState, Kind, Method, Policy
from openwrtgui.net.apply import NetApplyResult, NetPlan
from openwrtgui.net.dhcp import DhcpRequest, HostRequest, V6Mode
from openwrtgui.net.dns import DnsRequest
from openwrtgui.net.interfaces import InterfaceRequest
from openwrtgui.net.model import Lease
from openwrtgui.net.routes import LiveTables, RouteRequest, RuleRequest
from openwrtgui.net.state import NetworkState

router = APIRouter(
    prefix="/api/routers/{router_id}/network", dependencies=[Depends(require_token)], tags=["network"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class NetPlanOut(BaseModel):
    """The preview: the lines with secrets already hidden, never the ops or the secrets themselves."""

    router_id: str
    screen: str
    lines: list[str]
    warnings: list[str]
    rollback: bool
    target_host: str | None
    digest: str

    @classmethod
    def of(cls, plan: NetPlan) -> NetPlanOut:
        return cls(
            router_id=plan.router_id,
            screen=plan.screen,
            lines=list(plan.lines),
            warnings=list(plan.warnings),
            rollback=plan.rollback,
            target_host=plan.target_host,
            digest=plan.digest,
        )


class Digest(BaseModel):
    digest: str  # the preview's: the router must not have changed since


class InterfaceIn(BaseModel):
    name: str
    create: bool = False
    delete: bool = False
    proto: str | None = None
    device: str | None = None
    address: str | None = None
    gateway: str | None = None
    dns: list[str] | None = None
    mtu: int | None = None
    bridge_ports: list[str] | None = None
    edits: list[OptionEditIn] = []

    def to_domain(self) -> InterfaceRequest:
        return InterfaceRequest(
            name=self.name,
            create=self.create,
            delete=self.delete,
            proto=self.proto,
            device=self.device,
            address=self.address,
            gateway=self.gateway,
            dns=tuple(self.dns) if self.dns is not None else None,
            mtu=self.mtu,
            bridge_ports=tuple(self.bridge_ports) if self.bridge_ports is not None else None,
            edits=tuple(OptionEdit(e.section, e.name, e.value) for e in self.edits),
        )


class InterfaceApplyIn(InterfaceIn, Digest):
    pass


class DhcpIn(BaseModel):
    interface: str
    enabled: bool | None = None
    start: int | None = None
    limit: int | None = None
    leasetime: str | None = None
    options: list[str] | None = None
    dhcpv6: V6Mode | None = None
    ra: V6Mode | None = None

    def to_domain(self) -> DhcpRequest:
        return DhcpRequest(
            self.interface,
            self.enabled,
            self.start,
            self.limit,
            self.leasetime,
            tuple(self.options) if self.options is not None else None,
            self.dhcpv6,
            self.ra,
        )


class DhcpApplyIn(DhcpIn, Digest):
    pass


class HostIn(BaseModel):
    section: str | None = None
    mac: str
    name: str | None = None
    ip: str | None = None
    leasetime: str | None = None
    gets_address: bool = True


class HostsIn(BaseModel):
    upserts: list[HostIn] = []
    deletes: list[str] = []

    def upserts_domain(self) -> list[HostRequest]:
        return [
            HostRequest(h.section, h.mac, h.name, h.ip, h.leasetime, h.gets_address) for h in self.upserts
        ]


class HostsApplyIn(HostsIn, Digest):
    pass


class OverrideIn(BaseModel):
    host: str
    ip: str


class DnsIn(BaseModel):
    forwarders: list[str] | None = None
    domain: str | None = None
    rebind_domains: list[str] | None = None
    overrides: list[OverrideIn] | None = None
    switches: dict[str, bool] = {}
    cachesize: int | Literal["default"] | None = None  # "default" removes it
    others: dict[str, str | None] = {}

    def to_domain(self) -> DnsRequest:
        return DnsRequest(
            forwarders=tuple(self.forwarders) if self.forwarders is not None else None,
            domain=self.domain,
            rebind_domains=tuple(self.rebind_domains) if self.rebind_domains is not None else None,
            overrides=tuple((o.host, o.ip) for o in self.overrides) if self.overrides is not None else None,
            switches=dict(self.switches),
            cachesize=self.cachesize,
            others=dict(self.others),
        )


class DnsApplyIn(DnsIn, Digest):
    pass


class RouteIn(BaseModel):
    section: str | None = None
    kind: Literal["route", "route6"] = "route"
    interface: str
    target: str
    gateway: str | None = None
    metric: int | None = None
    table: str | None = None
    type: str | None = None
    disabled: bool = False


class RuleIn(BaseModel):
    section: str | None = None
    kind: Literal["rule", "rule6"] = "rule"
    src: str | None = None
    dest: str | None = None
    in_iface: str | None = None
    out_iface: str | None = None
    lookup: str | None = None
    priority: int | None = None
    action: str | None = None
    disabled: bool = False


class RoutesIn(BaseModel):
    upserts: list[RouteIn] = []
    deletes: list[str] = []
    rule_upserts: list[RuleIn] = []
    rule_deletes: list[str] = []

    def to_domain(self) -> tuple[list[RouteRequest], list[str], list[RuleRequest], list[str]]:
        return (
            [RouteRequest(**r.model_dump()) for r in self.upserts],
            list(self.deletes),
            [RuleRequest(**r.model_dump()) for r in self.rule_upserts],
            list(self.rule_deletes),
        )


class RoutesApplyIn(RoutesIn, Digest):
    pass


class AccessIn(BaseModel):
    kind: Kind
    sections: list[str]
    policy: Policy | None = None
    mac: str | None = None
    method: Method | None = None
    seconds: int | None = Field(default=None, ge=0)

    def to_domain(self) -> AccessChange:
        return AccessChange(self.kind, tuple(self.sections), self.policy, self.mac, self.method, self.seconds)


class AccessApplyIn(AccessIn, Digest):
    pass


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def network_state(router_id: str, ctx: Ctx) -> NetworkState:
    return await ctx.net.state(_known(ctx, router_id))


@router.get("/interfaces/{name}/options")
async def interface_options(router_id: str, name: str, ctx: Ctx) -> list[OptionRow]:
    return await ctx.net.interface_options(_known(ctx, router_id), name)


@router.post("/interfaces/preview")
async def interface_preview(router_id: str, body: InterfaceIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.net.plan_interface(_known(ctx, router_id), body.to_domain()))


@router.post("/interfaces/apply")
async def interface_apply(router_id: str, body: InterfaceApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_interface(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/dhcp/preview")
async def dhcp_preview(router_id: str, body: DhcpIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.net.plan_dhcp(_known(ctx, router_id), body.to_domain()))


@router.post("/dhcp/apply")
async def dhcp_apply(router_id: str, body: DhcpApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_dhcp(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/hosts/preview")
async def hosts_preview(router_id: str, body: HostsIn, ctx: Ctx) -> NetPlanOut:
    plan = await ctx.net.plan_hosts(_known(ctx, router_id), body.upserts_domain(), body.deletes)
    return NetPlanOut.of(plan)


@router.post("/hosts/apply")
async def hosts_apply(router_id: str, body: HostsApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_hosts(_known(ctx, router_id), body.upserts_domain(), body.deletes, body.digest)


@router.get("/leases")
async def leases(router_id: str, ctx: Ctx) -> list[Lease]:
    return await ctx.net.leases(_known(ctx, router_id))


@router.post("/dns/preview")
async def dns_preview(router_id: str, body: DnsIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.net.plan_dns(_known(ctx, router_id), body.to_domain()))


@router.post("/dns/apply")
async def dns_apply(router_id: str, body: DnsApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_dns(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/routes/preview")
async def routes_preview(router_id: str, body: RoutesIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.net.plan_routes(_known(ctx, router_id), *body.to_domain()))


@router.post("/routes/apply")
async def routes_apply(router_id: str, body: RoutesApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_routes(_known(ctx, router_id), *body.to_domain(), digest=body.digest)


@router.get("/routes/live")
async def routes_live(router_id: str, ctx: Ctx) -> LiveTables:
    return await ctx.net.live_routes(_known(ctx, router_id))


@router.get("/access")
async def access_state(router_id: str, ctx: Ctx) -> AccessState:
    return await ctx.net.access(_known(ctx, router_id))


@router.post("/access/preview")
async def access_preview(router_id: str, body: AccessIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.net.plan_access(_known(ctx, router_id), body.to_domain()))


@router.post("/access/apply")
async def access_apply(router_id: str, body: AccessApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.net.apply_access(_known(ctx, router_id), body.to_domain(), body.digest)
