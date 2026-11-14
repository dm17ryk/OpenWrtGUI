"""Mount points with block-mount endpoints (v1.0a2 D5): fstab edits, Generate Config, Unmount, Mount attached
devices."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.system.fstab import FstabChange, FstabState

router = APIRouter(
    prefix="/api/routers/{router_id}/system/fstab", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class FstabApplyIn(FstabChange):
    digest: str


class UnmountIn(BaseModel):
    target: str


class UnmountApplyIn(UnmountIn):
    digest: str


@router.get("")
async def fstab(router_id: str, ctx: Ctx) -> FstabState:
    return await ctx.fstab.state(_known(ctx, router_id))


@router.post("/preview")
async def preview(router_id: str, body: FstabChange, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fstab.plan(_known(ctx, router_id), body))


@router.post("/apply")
async def apply(router_id: str, body: FstabApplyIn, ctx: Ctx) -> NetApplyResult:
    change = FstabChange.model_validate(body.model_dump(exclude={"digest"}))
    return await ctx.fstab.apply(_known(ctx, router_id), change, body.digest)


@router.post("/generate/preview")
async def generate_preview(router_id: str, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fstab.plan_generate(_known(ctx, router_id)))


@router.post("/generate/apply")
async def generate_apply(router_id: str, body: Digest, ctx: Ctx) -> NetApplyResult:
    return await ctx.fstab.apply_generate(_known(ctx, router_id), body.digest)


@router.post("/unmount/preview")
async def unmount_preview(router_id: str, body: UnmountIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fstab.plan_unmount(_known(ctx, router_id), body.target))


@router.post("/unmount/apply")
async def unmount_apply(router_id: str, body: UnmountApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.fstab.apply_unmount(_known(ctx, router_id), body.target, body.digest)


@router.post("/mount/preview")
async def mount_preview(router_id: str, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.fstab.plan_mount(_known(ctx, router_id)))


@router.post("/mount/apply")
async def mount_apply(router_id: str, body: Digest, ctx: Ctx) -> NetApplyResult:
    return await ctx.fstab.apply_mount(_known(ctx, router_id), body.digest)
