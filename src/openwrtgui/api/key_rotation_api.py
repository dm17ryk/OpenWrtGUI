"""App key rotation (spec 7.12, v1.1b D8): preview, start with the preview's digest, the job, retry, stop."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import Ok
from openwrtgui.api.net_api import Digest
from openwrtgui.context import AppContext
from openwrtgui.onboard.rotate import RotationJob, RotationPreview

router = APIRouter(prefix="/api/app-key/rotation", dependencies=[Depends(require_token)], tags=["app"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.post("/preview")
async def rotation_preview(ctx: Ctx) -> RotationPreview:
    """What the rotation would do, router by router; reads only."""
    return ctx.key_rotation.preview()


@router.post("")
async def rotation_start(body: Digest, ctx: Ctx) -> RotationJob:
    """409 while it runs or when the router list changed since the preview; 423 during a harness run."""
    return await ctx.key_rotation.start(body.digest)


@router.get("")
async def rotation_job(ctx: Ctx) -> RotationJob | None:
    return ctx.key_rotation.job()


@router.post("/{router_id}/retry")
async def rotation_retry(router_id: str, ctx: Ctx) -> RotationJob:
    return await ctx.key_rotation.retry(router_id)


@router.post("/stop")
async def rotation_stop(ctx: Ctx) -> Ok:
    """Stops between routers: each router is left on one key or both, never on none."""
    ctx.key_rotation.request_stop()
    return Ok()
