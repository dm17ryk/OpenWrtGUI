"""The LTE modem screen's endpoints (spec 7.10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.lte.service import LteAction, LteBusy
from openwrtgui.lte.state import LteState
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(prefix="/api/routers/{router_id}/lte", dependencies=[Depends(require_token)], tags=["lte"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class ActionIn(BaseModel):
    action: LteAction


class ActionApplyIn(ActionIn, Digest):
    pass


@router.get("")
async def lte_state(router_id: str, ctx: Ctx) -> LteState:
    return await ctx.lte.state(_known(ctx, router_id))


@router.post("/action/preview")
async def action_preview(router_id: str, body: ActionIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.lte.plan_action(_known(ctx, router_id), body.action))


@router.post("/action/apply")
async def action_apply(router_id: str, body: ActionApplyIn, ctx: Ctx) -> NetApplyResult:
    try:
        return await ctx.lte.apply_action(_known(ctx, router_id), body.action, body.digest)
    except LteBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
