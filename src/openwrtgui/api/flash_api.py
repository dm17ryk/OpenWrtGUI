"""Flash a router from an imported image: the exact preview, the start, and the job's progress."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest
from openwrtgui.context import AppContext
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.flash.service import FlashJob

router = APIRouter(prefix="/api/routers/{router_id}", dependencies=[Depends(require_token)], tags=["flash"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


class FlashIn(BaseModel):
    board: str
    revision: str
    sha256: str
    keep_settings: bool = True
    isolated: bool = False

    def to_domain(self) -> FlashRequest:
        return FlashRequest(**self.model_dump())


class FlashStartIn(FlashIn, Digest):
    pass


class FlashPlanOut(BaseModel):
    lines: list[str]
    warnings: list[str]
    digest: str


def _name(ctx: AppContext, router_id: str) -> str:
    rec = ctx.routers.get(router_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return rec.name


@router.post("/flash/preview")
async def flash_preview(router_id: str, body: FlashIn, ctx: Ctx) -> FlashPlanOut:
    _name(ctx, router_id)
    plan = await ctx.flash.plan(router_id, body.to_domain())
    return FlashPlanOut(lines=list(plan.lines), warnings=list(plan.warnings), digest=plan.digest)


@router.post("/flash/start")
async def flash_start(router_id: str, body: FlashStartIn, ctx: Ctx) -> FlashJob:
    name = _name(ctx, router_id)
    if ctx.flash.running(router_id):
        raise HTTPException(status_code=409, detail=f"A flash is already running on {name}")
    return await ctx.flash.start(router_id, body.to_domain(), body.digest)


@router.get("/flash")
async def flash_job(router_id: str, ctx: Ctx) -> FlashJob | None:
    _name(ctx, router_id)
    return ctx.flash.job(router_id)
