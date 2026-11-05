"""Ports, VLANs, mirroring per router: state, exact previews and applies."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.ports.compile import MirrorRequest, VlanRequest
from openwrtgui.ports.state import PortsState

router = APIRouter(
    prefix="/api/routers/{router_id}/ports", dependencies=[Depends(require_token)], tags=["ports"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class PortEnableIn(BaseModel):
    port: int | None = None
    on: bool | None = None
    all_on: bool = False


class PortEnableApplyIn(PortEnableIn, Digest):
    pass


class VlanIn(BaseModel):
    section: str | None = None
    vlan: int
    members: dict[int, Literal["u", "t"]]


class VlansIn(BaseModel):
    upserts: list[VlanIn] = []
    deletes: list[str] = []

    def upserts_domain(self) -> list[VlanRequest]:
        return [VlanRequest(v.section, v.vlan, dict(v.members)) for v in self.upserts]


class VlansApplyIn(VlansIn, Digest):
    pass


class MirrorSourceIn(BaseModel):
    port: int
    rx: bool = False
    tx: bool = False


class MirrorIn(BaseModel):
    monitor: int | None = None
    sources: list[MirrorSourceIn] = []

    def to_domain(self) -> MirrorRequest:
        return MirrorRequest(self.monitor, {s.port: (s.rx, s.tx) for s in self.sources})


class MirrorApplyIn(MirrorIn, Digest):
    pass


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def ports_state(router_id: str, ctx: Ctx) -> PortsState:
    return await ctx.ports.state(_known(ctx, router_id))


@router.post("/enable/preview")
async def enable_preview(router_id: str, body: PortEnableIn, ctx: Ctx) -> NetPlanOut:
    plan = await ctx.ports.plan_ports(_known(ctx, router_id), body.port, body.on, all_on=body.all_on)
    return NetPlanOut.of(plan)


@router.post("/enable/apply")
async def enable_apply(router_id: str, body: PortEnableApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.ports.apply_ports(
        _known(ctx, router_id), body.port, body.on, body.digest, all_on=body.all_on
    )


@router.post("/vlans/preview")
async def vlans_preview(router_id: str, body: VlansIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(
        await ctx.ports.plan_vlans(_known(ctx, router_id), body.upserts_domain(), body.deletes)
    )


@router.post("/vlans/apply")
async def vlans_apply(router_id: str, body: VlansApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.ports.apply_vlans(
        _known(ctx, router_id), body.upserts_domain(), body.deletes, body.digest
    )


@router.post("/mirror/preview")
async def mirror_preview(router_id: str, body: MirrorIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.ports.plan_mirror(_known(ctx, router_id), body.to_domain()))


@router.post("/mirror/apply")
async def mirror_apply(router_id: str, body: MirrorApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.ports.apply_mirror(_known(ctx, router_id), body.to_domain(), body.digest)
