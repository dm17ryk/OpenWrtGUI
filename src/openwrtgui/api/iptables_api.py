"""Legacy iptables endpoints (v1.0a2 D6): LuCI's iptables view, Reset counters, Restart firewall."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.fw.iptables import IptablesPresence, IptablesState
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(
    prefix="/api/routers/{router_id}/firewall/iptables",
    dependencies=[Depends(require_token)],
    tags=["firewall"],
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def iptables(router_id: str, ctx: Ctx) -> IptablesState:
    return await ctx.iptables.state(_known(ctx, router_id))


@router.get("/present")
async def present(router_id: str, ctx: Ctx) -> IptablesPresence:
    return await ctx.iptables.presence(_known(ctx, router_id))


@router.post("/reset/preview")
async def reset_preview(router_id: str, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.iptables.plan_reset(_known(ctx, router_id)))


@router.post("/reset/apply")
async def reset_apply(router_id: str, body: Digest, ctx: Ctx) -> NetApplyResult:
    return await ctx.iptables.apply_reset(_known(ctx, router_id), body.digest)


@router.post("/restart/preview")
async def restart_preview(router_id: str, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.iptables.plan_restart(_known(ctx, router_id)))


@router.post("/restart/apply")
async def restart_apply(router_id: str, body: Digest, ctx: Ctx) -> NetApplyResult:
    return await ctx.iptables.apply_restart(_known(ctx, router_id), body.digest)
