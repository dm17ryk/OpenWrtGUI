"""Discovery per router: how it differs from its image, the firmware check, copies and reflash checklists."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.discovery.checklist import ReflashChecklist
from openwrtgui.discovery.copy import CopyRequest
from openwrtgui.discovery.firmware import FirmwareCheck
from openwrtgui.discovery.state import DiscoveryState
from openwrtgui.images.profile import ProfileKey
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(
    prefix="/api/routers/{router_id}", dependencies=[Depends(require_token)], tags=["discovery"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class CopyIn(BaseModel):
    paths: list[str]
    target: str
    from_checklist: str | None = None

    def to_domain(self) -> CopyRequest:
        return CopyRequest(paths=tuple(self.paths), target=self.target, from_checklist=self.from_checklist)


class CopyApplyIn(CopyIn, Digest):
    pass


class ChecklistInfo(BaseModel):
    """A saved checklist without the file contents."""

    stamp: str
    saved_at: datetime
    profile: ProfileKey | None
    lost: list[str]
    restorable: list[str]
    packages_added: list[str]

    @classmethod
    def of(cls, c: ReflashChecklist) -> ChecklistInfo:
        return cls(
            stamp=c.stamp,
            saved_at=c.saved_at,
            profile=c.profile,
            lost=[f.path for f in c.lost],
            restorable=[f.path for f in c.lost if f.kind == "link" or f.data is not None],
            packages_added=[p.name for p in c.packages_added],
        )


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/discovery")
async def discovery_state(router_id: str, ctx: Ctx) -> DiscoveryState:
    return await ctx.discovery.state(_known(ctx, router_id))


@router.post("/discovery/firmware")
async def firmware_check(router_id: str, ctx: Ctx) -> FirmwareCheck:
    return await ctx.discovery.check_firmware(_known(ctx, router_id))


@router.post("/discovery/copy/preview")
async def copy_preview(router_id: str, body: CopyIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.discovery.plan_copy(_known(ctx, router_id), body.to_domain()))


@router.post("/discovery/copy/apply")
async def copy_apply(router_id: str, body: CopyApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.discovery.apply_copy(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/discovery/checklist")
async def save_checklist(router_id: str, ctx: Ctx) -> ChecklistInfo:
    return ChecklistInfo.of(await ctx.discovery.save_checklist(_known(ctx, router_id)))


@router.get("/discovery/checklists")
async def checklists(router_id: str, ctx: Ctx) -> list[ChecklistInfo]:
    found = ctx.discovery.checklists.list(_known(ctx, router_id))
    return [ChecklistInfo.of(c) for c in reversed(found)]
