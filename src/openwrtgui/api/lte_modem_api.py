"""The LTE screen's SIM, SMS and USSD endpoints (v1.3b E1), under the LTE screen's prefix. `GET /lte` keeps
its pinned read count: each card reads its own endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.lte.modem import PinRefused, PinResult
from openwrtgui.lte.sim import SimState

router = APIRouter(prefix="/api/routers/{router_id}/lte", dependencies=[Depends(require_token)], tags=["lte"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class PinIn(BaseModel):
    """E4: never stored, logged or returned; the 422 handler drops the input it would echo."""

    pin: str = Field(repr=False, max_length=16)


@router.get("/sim")
async def sim(router_id: str, ctx: Ctx) -> SimState:
    return await ctx.lte_modem.sim(_known(ctx, router_id))


@router.post("/sim/pin")
async def enter_pin(router_id: str, body: PinIn, ctx: Ctx) -> PinResult:
    """409 when the SIM does not ask for a PIN, is blocked or has one try left (E3), or another LTE write or
    Recover holds the router; 423 during a harness run."""
    try:
        return await ctx.lte_modem.enter_pin(_known(ctx, router_id), body.pin)
    except PinRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
