"""System › Access, LEDs and Mount points endpoints (spec 7.11, v0.6c plan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.system.access_service import AccessState, LedState, MountState

router = APIRouter(
    prefix="/api/routers/{router_id}/system", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/access")
async def access(router_id: str, ctx: Ctx) -> AccessState:
    return await ctx.access.access(_known(ctx, router_id))


@router.get("/leds")
async def leds(router_id: str, ctx: Ctx) -> LedState:
    return await ctx.access.leds(_known(ctx, router_id))


@router.get("/mounts")
async def mounts(router_id: str, ctx: Ctx) -> MountState:
    return await ctx.access.mounts(_known(ctx, router_id))
