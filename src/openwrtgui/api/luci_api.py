"""LuCI fallback pages per router: list, open a bridge, see what changed, close it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.luci_bridge.pages import PageView
from openwrtgui.luci_bridge.service import BridgeClosed, BridgeView, UciChange

router = APIRouter(
    prefix="/api/routers/{router_id}/luci", dependencies=[Depends(require_token)], tags=["luci"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class OpenIn(BaseModel):
    path: str


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


def _bridge(ctx: AppContext, router_id: str, bridge_id: str) -> str:
    try:
        view = ctx.luci.view(bridge_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="This LuCI page is closed") from None
    if view.router_id != router_id:
        raise HTTPException(status_code=404, detail="This LuCI page is closed")
    return bridge_id


@router.get("/pages")
async def luci_pages(router_id: str, ctx: Ctx) -> list[PageView]:
    return await ctx.luci.pages(_known(ctx, router_id))


@router.post("/open")
async def luci_open(router_id: str, body: OpenIn, ctx: Ctx) -> BridgeView:
    return await ctx.luci.open(_known(ctx, router_id), body.path)


@router.get("/bridges/{bridge_id}")
async def luci_bridge(router_id: str, bridge_id: str, ctx: Ctx) -> BridgeView:
    """The bridge as it is now: `access` turns to read when Bench Guard sees a run."""
    return ctx.luci.view(_bridge(ctx, router_id, bridge_id))


@router.get("/bridges/{bridge_id}/changes")
async def luci_changes(router_id: str, bridge_id: str, ctx: Ctx) -> list[UciChange]:
    return list(await ctx.luci.changes(_bridge(ctx, router_id, bridge_id)))


@router.post("/bridges/{bridge_id}/close")
async def luci_close(router_id: str, bridge_id: str, ctx: Ctx) -> BridgeClosed:
    return await ctx.luci.close(_bridge(ctx, router_id, bridge_id))
