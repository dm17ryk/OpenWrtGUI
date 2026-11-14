"""System › Plugins endpoints (v1.0a2 D4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.system.plugins import PluginChange, PluginState

router = APIRouter(
    prefix="/api/routers/{router_id}/system/plugins", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class PluginApplyIn(PluginChange):
    digest: str


@router.get("")
async def plugins(router_id: str, ctx: Ctx) -> PluginState:
    return await ctx.plugins.state(_known(ctx, router_id))


@router.post("/preview")
async def preview(router_id: str, body: PluginChange, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.plugins.plan(_known(ctx, router_id), body))


@router.post("/apply")
async def apply(router_id: str, body: PluginApplyIn, ctx: Ctx) -> NetApplyResult:
    change = PluginChange.model_validate(body.model_dump(exclude={"digest"}))
    return await ctx.plugins.apply(_known(ctx, router_id), change, body.digest)
