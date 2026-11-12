"""RF live per router radio: channel analysis (v0.7 plan D13) and frame analysis (D12)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.rf.air import RADIO
from openwrtgui.rf.frames_service import FrameAnalyzer, FramePlan, FrameState
from openwrtgui.rf.scan_service import ScanPlan, ScanResult, Via

router = APIRouter(
    prefix="/api/routers/{router_id}/rf/{radio}", dependencies=[Depends(require_token)], tags=["rf"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class DigestIn(BaseModel):
    digest: str  # the preview's: what runs is what was shown


class ScanPlanOut(BaseModel):
    via: Via
    lines: list[str]
    warnings: list[str]
    digest: str

    @classmethod
    def of(cls, plan: ScanPlan) -> ScanPlanOut:
        return cls(via=plan.via, lines=list(plan.lines), warnings=list(plan.warnings), digest=plan.digest)


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/scan")
async def scan_last(router_id: str, radio: str, ctx: Ctx) -> ScanResult | None:
    return ctx.scans.last(_known(ctx, router_id), radio)


@router.post("/scan/preview")
async def scan_preview(router_id: str, radio: str, ctx: Ctx) -> ScanPlanOut:
    return ScanPlanOut.of(await ctx.scans.preview(_known(ctx, router_id), radio))


@router.post("/scan")
async def scan_run(router_id: str, radio: str, body: DigestIn, ctx: Ctx) -> ScanResult:
    return await ctx.scans.scan(_known(ctx, router_id), radio, body.digest)


class FramePlanOut(BaseModel):
    lines: list[str]
    warnings: list[str]
    digest: str

    @classmethod
    def of(cls, plan: FramePlan) -> FramePlanOut:
        return cls(lines=list(plan.lines), warnings=list(plan.warnings), digest=plan.digest)


def _frames(ctx: AppContext, router_id: str, radio: str) -> FrameAnalyzer:
    if not RADIO.fullmatch(radio):
        raise HTTPException(status_code=422, detail=f"{radio!r} is not a radio name")
    return ctx.rf.frames(_known(ctx, router_id), radio)


@router.get("/frames")
async def frames_state(router_id: str, radio: str, ctx: Ctx) -> FrameState:
    return _frames(ctx, router_id, radio).state()


@router.post("/frames/preview")
async def frames_preview(router_id: str, radio: str, ctx: Ctx) -> FramePlanOut:
    return FramePlanOut.of(await _frames(ctx, router_id, radio).preview())


@router.post("/frames/start")
async def frames_start(router_id: str, radio: str, body: DigestIn, ctx: Ctx) -> FrameState:
    return await _frames(ctx, router_id, radio).start(body.digest)


@router.post("/frames/stop")
async def frames_stop(router_id: str, radio: str, ctx: Ctx) -> FrameState:
    return await _frames(ctx, router_id, radio).stop()
