"""Discovery per router: how it differs from its image, the firmware check, copies and reflash checklists."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.discovery.checklist import ReflashChecklist
from openwrtgui.discovery.copy import CopyRequest
from openwrtgui.discovery.firmware import FirmwareCheck
from openwrtgui.discovery.service import HelpResult
from openwrtgui.discovery.state import DiscoveryState
from openwrtgui.discovery.tools import ToolCard, check_card, prefill_card
from openwrtgui.images.profile import ProfileKey
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(
    prefix="/api/routers/{router_id}", dependencies=[Depends(require_token)], tags=["discovery"]
)
tools = APIRouter(prefix="/api/tools", dependencies=[Depends(require_token)], tags=["discovery"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


class HelpIn(BaseModel):
    path: str


class HelpApplyIn(HelpIn, Digest):
    pass


class ToolIn(BaseModel):
    path: str
    label: str
    values: dict[str, str] = {}


class ToolApplyIn(ToolIn, Digest):
    pass


class PrefillIn(BaseModel):
    path: str
    usage: str | None = None


class ServiceIn(BaseModel):
    name: str
    action: Literal["start", "stop", "restart"]


class ServiceApplyIn(ServiceIn, Digest):
    pass


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


@router.post("/discovery/help/preview")
async def help_preview(router_id: str, body: HelpIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.discovery.plan_help(_known(ctx, router_id), body.path))


@router.post("/discovery/help/apply")
async def help_apply(router_id: str, body: HelpApplyIn, ctx: Ctx) -> HelpResult:
    return await ctx.discovery.apply_help(_known(ctx, router_id), body.path, body.digest)


@router.post("/discovery/tool/preview")
async def tool_preview(router_id: str, body: ToolIn, ctx: Ctx) -> NetPlanOut:
    plan = await ctx.discovery.plan_tool(_known(ctx, router_id), body.path, body.label, body.values)
    return NetPlanOut.of(plan)


@router.post("/discovery/tool/apply")
async def tool_apply(router_id: str, body: ToolApplyIn, ctx: Ctx) -> HelpResult:
    rid = _known(ctx, router_id)
    return await ctx.discovery.apply_tool(rid, body.path, body.label, body.values, body.digest)


@router.post("/discovery/service/preview")
async def service_preview(router_id: str, body: ServiceIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.discovery.plan_service(_known(ctx, router_id), body.name, body.action))


@router.post("/discovery/service/apply")
async def service_apply(router_id: str, body: ServiceApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.discovery.apply_service(_known(ctx, router_id), body.name, body.action, body.digest)


@tools.get("/{board}")
async def tool_cards(board: str, ctx: Ctx) -> list[ToolCard]:
    return ctx.discovery.tools.cards(board)


@tools.put("/{board}")
async def save_tool_card(board: str, body: ToolCard, ctx: Ctx) -> ToolCard:
    if body.board != board:
        raise ValueError(f"This card is for {body.board}, not {board}")
    check_card(body)
    ctx.discovery.tools.save(body)
    return body


@tools.delete("/{board}", status_code=204)
async def delete_tool_card(board: str, path: str, ctx: Ctx) -> None:
    ctx.discovery.tools.delete(board, path)


@tools.post("/{board}/prefill")
async def prefill(board: str, body: PrefillIn) -> ToolCard:
    return prefill_card(board, body.path, body.usage)
