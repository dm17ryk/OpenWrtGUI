"""The Firewall per router: state, the raw ruleset, exact previews and applies."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.fw.compile import ForwardingRequest, ModelRequest, ZoneRequest
from openwrtgui.fw.custom import CustomRequest
from openwrtgui.fw.sections import ForwardRequest, IpsetRequest, Kind, NatRequest, RuleRequest, SectionRequest
from openwrtgui.fw.state import FirewallState
from openwrtgui.fw.tables import ChainEdit, TableRequest
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(
    prefix="/api/routers/{router_id}/firewall", dependencies=[Depends(require_token)], tags=["firewall"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]
PolicyIn = Literal["ACCEPT", "REJECT", "DROP"]


class RulesetOut(BaseModel):
    text: str


class ModelIn(BaseModel):
    cells: dict[str, PolicyIn]
    pins_removed: list[Literal["ssh", "dhcpdns"]] = []

    def to_domain(self) -> ModelRequest:
        return ModelRequest(dict(self.cells), frozenset(self.pins_removed))


class ModelApplyIn(ModelIn, Digest):
    pass


class ZoneIn(BaseModel):
    section: str | None = None
    name: str
    networks: list[str] = []
    input: PolicyIn
    output: PolicyIn
    forward: PolicyIn
    masq: bool = False
    mtu_fix: bool = False
    others: dict[str, str | None] = {}

    def to_domain(self) -> ZoneRequest:
        return ZoneRequest(
            self.section,
            self.name,
            tuple(self.networks),
            self.input,
            self.output,
            self.forward,
            self.masq,
            self.mtu_fix,
            dict(self.others),
        )


class ForwardingIn(BaseModel):
    src: str
    dest: str


class ZonesIn(BaseModel):
    upserts: list[ZoneIn] = []
    deletes: list[str] = []
    forwardings: list[ForwardingIn] | None = None

    def domain(self) -> tuple[list[ZoneRequest], list[str], list[ForwardingRequest] | None]:
        forwardings = (
            [ForwardingRequest(f.src, f.dest) for f in self.forwardings]
            if self.forwardings is not None
            else None
        )
        return [z.to_domain() for z in self.upserts], self.deletes, forwardings


class ZonesApplyIn(ZonesIn, Digest):
    pass


class TrafficRuleIn(BaseModel):
    section: str | None = None
    name: str
    src: str | None = None
    dest: str | None = None
    proto: str | None = None
    src_ip: list[str] = []
    dest_ip: list[str] = []
    src_port: str | None = None
    dest_port: str | None = None
    icmp_type: list[str] = []
    family: Literal["ipv4", "ipv6", "any"] = "any"
    target: Literal["ACCEPT", "REJECT", "DROP"] = "ACCEPT"
    enabled: bool = True
    others: dict[str, str | None] = {}

    def to_domain(self) -> RuleRequest:
        return RuleRequest(
            self.section,
            self.name,
            self.src,
            self.dest,
            self.proto,
            tuple(self.src_ip),
            tuple(self.dest_ip),
            self.src_port,
            self.dest_port,
            tuple(self.icmp_type),
            self.family,
            self.target,
            self.enabled,
            dict(self.others),
        )


class ForwardIn(BaseModel):
    section: str | None = None
    name: str
    src: str = "wan"
    src_dport: str
    dest: str = "lan"
    dest_ip: str
    dest_port: str | None = None
    proto: str = "tcp udp"
    enabled: bool = True
    others: dict[str, str | None] = {}

    def to_domain(self) -> ForwardRequest:
        return ForwardRequest(
            self.section,
            self.name,
            self.src,
            self.src_dport,
            self.dest,
            self.dest_ip,
            self.dest_port,
            self.proto,
            self.enabled,
            dict(self.others),
        )


class NatIn(BaseModel):
    section: str | None = None
    name: str
    src: str
    src_ip: str | None = None
    dest_ip: str | None = None
    dest_port: str | None = None
    proto: str | None = None
    target: Literal["SNAT", "MASQUERADE", "ACCEPT"] = "SNAT"
    snat_ip: str | None = None
    snat_port: str | None = None
    enabled: bool = True
    others: dict[str, str | None] = {}

    def to_domain(self) -> NatRequest:
        return NatRequest(
            self.section,
            self.name,
            self.src,
            self.src_ip,
            self.dest_ip,
            self.dest_port,
            self.proto,
            self.target,
            self.snat_ip,
            self.snat_port,
            self.enabled,
            dict(self.others),
        )


class IpsetIn(BaseModel):
    section: str | None = None
    name: str
    family: Literal["ipv4", "ipv6"] = "ipv4"
    match: list[str]
    entries: list[str] = []
    enabled: bool = True
    others: dict[str, str | None] = {}

    def to_domain(self) -> IpsetRequest:
        return IpsetRequest(
            self.section,
            self.name,
            self.family,
            tuple(self.match),
            tuple(self.entries),
            self.enabled,
            dict(self.others),
        )


class RulesIn(BaseModel):
    upserts: list[TrafficRuleIn] = []
    deletes: list[str] = []


class ForwardsIn(BaseModel):
    upserts: list[ForwardIn] = []
    deletes: list[str] = []


class NatsIn(BaseModel):
    upserts: list[NatIn] = []
    deletes: list[str] = []


class IpsetsIn(BaseModel):
    upserts: list[IpsetIn] = []
    deletes: list[str] = []


class RulesApplyIn(RulesIn, Digest):
    pass


class ForwardsApplyIn(ForwardsIn, Digest):
    pass


class NatsApplyIn(NatsIn, Digest):
    pass


class IpsetsApplyIn(IpsetsIn, Digest):
    pass


class CustomIn(BaseModel):
    name: str
    content: str | None = None

    def to_domain(self) -> CustomRequest:
        return CustomRequest(self.name, self.content)


class CustomApplyIn(CustomIn, Digest):
    pass


class ChainIn(BaseModel):
    name: str
    declaration: str | None = None


class TableRuleIn(BaseModel):
    chain: str
    body: str


class TableIn(BaseModel):
    key: str = ""
    action: Literal["edit", "add", "delete"]
    override: bool = False
    family: str | None = None
    name: str | None = None
    chains: list[ChainIn] = []
    rules: list[TableRuleIn] = []
    keep: Literal["runtime", "include"] = "runtime"

    def to_domain(self) -> TableRequest:
        return TableRequest(
            self.key,
            self.action,
            self.override,
            self.family,
            self.name,
            tuple(ChainEdit(c.name, c.declaration) for c in self.chains),
            tuple((r.chain, r.body) for r in self.rules),
            self.keep,
        )


class TableApplyIn(TableIn, Digest):
    pass


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def firewall_state(router_id: str, ctx: Ctx) -> FirewallState:
    return await ctx.fw.state(_known(ctx, router_id))


@router.get("/ruleset")
async def ruleset(router_id: str, ctx: Ctx) -> RulesetOut:
    return RulesetOut(text=await ctx.fw.ruleset_text(_known(ctx, router_id)))


@router.post("/model/preview")
async def model_preview(router_id: str, body: ModelIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fw.plan_model(_known(ctx, router_id), body.to_domain()))


@router.post("/model/apply")
async def model_apply(router_id: str, body: ModelApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.fw.apply_model(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/zones/preview")
async def zones_preview(router_id: str, body: ZonesIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fw.plan_zones(_known(ctx, router_id), *body.domain()))


@router.post("/zones/apply")
async def zones_apply(router_id: str, body: ZonesApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.fw.apply_zones(_known(ctx, router_id), *body.domain(), body.digest)


async def _sections_preview(
    ctx: AppContext, router_id: str, kind: Kind, upserts: list[SectionRequest], deletes: list[str]
) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fw.plan_sections(_known(ctx, router_id), kind, upserts, deletes))


async def _sections_apply(
    ctx: AppContext,
    router_id: str,
    kind: Kind,
    upserts: list[SectionRequest],
    deletes: list[str],
    digest: str,
) -> NetApplyResult:
    return await ctx.fw.apply_sections(_known(ctx, router_id), kind, upserts, deletes, digest)


@router.post("/rules/preview")
async def rules_preview(router_id: str, body: RulesIn, ctx: Ctx) -> NetPlanOut:
    return await _sections_preview(
        ctx, router_id, "rule", [r.to_domain() for r in body.upserts], body.deletes
    )


@router.post("/rules/apply")
async def rules_apply(router_id: str, body: RulesApplyIn, ctx: Ctx) -> NetApplyResult:
    upserts: list[SectionRequest] = [r.to_domain() for r in body.upserts]
    return await _sections_apply(ctx, router_id, "rule", upserts, body.deletes, body.digest)


@router.post("/forwards/preview")
async def forwards_preview(router_id: str, body: ForwardsIn, ctx: Ctx) -> NetPlanOut:
    return await _sections_preview(
        ctx, router_id, "redirect", [r.to_domain() for r in body.upserts], body.deletes
    )


@router.post("/forwards/apply")
async def forwards_apply(router_id: str, body: ForwardsApplyIn, ctx: Ctx) -> NetApplyResult:
    upserts: list[SectionRequest] = [r.to_domain() for r in body.upserts]
    return await _sections_apply(ctx, router_id, "redirect", upserts, body.deletes, body.digest)


@router.post("/nat/preview")
async def nat_preview(router_id: str, body: NatsIn, ctx: Ctx) -> NetPlanOut:
    return await _sections_preview(ctx, router_id, "nat", [r.to_domain() for r in body.upserts], body.deletes)


@router.post("/nat/apply")
async def nat_apply(router_id: str, body: NatsApplyIn, ctx: Ctx) -> NetApplyResult:
    upserts: list[SectionRequest] = [r.to_domain() for r in body.upserts]
    return await _sections_apply(ctx, router_id, "nat", upserts, body.deletes, body.digest)


@router.post("/ipsets/preview")
async def ipsets_preview(router_id: str, body: IpsetsIn, ctx: Ctx) -> NetPlanOut:
    return await _sections_preview(
        ctx, router_id, "ipset", [r.to_domain() for r in body.upserts], body.deletes
    )


@router.post("/ipsets/apply")
async def ipsets_apply(router_id: str, body: IpsetsApplyIn, ctx: Ctx) -> NetApplyResult:
    upserts: list[SectionRequest] = [r.to_domain() for r in body.upserts]
    return await _sections_apply(ctx, router_id, "ipset", upserts, body.deletes, body.digest)


@router.post("/custom/preview")
async def custom_preview(router_id: str, body: CustomIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fw.plan_custom(_known(ctx, router_id), body.to_domain()))


@router.post("/custom/apply")
async def custom_apply(router_id: str, body: CustomApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.fw.apply_custom(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/tables/preview")
async def tables_preview(router_id: str, body: TableIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fw.plan_table(_known(ctx, router_id), body.to_domain()))


@router.post("/tables/apply")
async def tables_apply(router_id: str, body: TableApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.fw.apply_table(_known(ctx, router_id), body.to_domain(), body.digest)
