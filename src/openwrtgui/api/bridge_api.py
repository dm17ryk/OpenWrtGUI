"""The VLAN editor on a DSA router (v1.0a3 D6): LuCI's Switch/VLAN config."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.ports.bridge import BridgeState
from openwrtgui.ports.bridge_rules import BridgeVlanRequest

router = APIRouter(
    prefix="/api/routers/{router_id}/ports/bridge", dependencies=[Depends(require_token)], tags=["ports"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class BridgeVlanIn(BaseModel):
    section: str | None = None
    vlan: int
    members: dict[str, Literal["u", "t"]]
    local: bool = True


class BridgeVlansIn(BaseModel):
    upserts: list[BridgeVlanIn] = []
    deletes: list[str] = []

    def upserts_domain(self) -> list[BridgeVlanRequest]:
        return [BridgeVlanRequest(v.section, v.vlan, dict(v.members), v.local) for v in self.upserts]


class BridgeVlansApplyIn(BridgeVlansIn, Digest):
    pass


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def bridge_state(router_id: str, ctx: Ctx) -> BridgeState:
    return await ctx.bridge_vlans.state(_known(ctx, router_id))


@router.post("/preview")
async def bridge_preview(router_id: str, body: BridgeVlansIn, ctx: Ctx) -> NetPlanOut:
    plan = await ctx.bridge_vlans.plan(_known(ctx, router_id), body.upserts_domain(), body.deletes)
    return NetPlanOut.of(plan)


@router.post("/apply")
async def bridge_apply(router_id: str, body: BridgeVlansApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.bridge_vlans.apply(
        _known(ctx, router_id), body.upserts_domain(), body.deletes, body.digest
    )
