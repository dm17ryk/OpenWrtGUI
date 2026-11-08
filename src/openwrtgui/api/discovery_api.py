"""Discovery per router: how it differs from its image, its custom packages, programs and capabilities."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.discovery.state import DiscoveryState

router = APIRouter(
    prefix="/api/routers/{router_id}", dependencies=[Depends(require_token)], tags=["discovery"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/discovery")
async def discovery_state(router_id: str, ctx: Ctx) -> DiscoveryState:
    return await ctx.discovery.state(_known(ctx, router_id))
