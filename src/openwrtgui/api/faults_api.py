"""Faults and capture per router: state, exact previews, arming, clearing, captures."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.capture.service import CaptureRequest, CaptureView
from openwrtgui.context import AppContext
from openwrtgui.faults.model import FaultRequest, NetemParams, TargetRef
from openwrtgui.faults.service import FaultsState
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(prefix="/api/routers/{router_id}", dependencies=[Depends(require_token)], tags=["faults"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


class TargetIn(BaseModel):
    mac: str | None = None
    ip: str | None = None


class NetemIn(BaseModel):
    delay_ms: int = 0
    jitter_ms: int = 0
    distribution: Literal["uniform", "normal", "pareto", "paretonormal"] = "uniform"
    loss_pct: float = 0
    reorder_pct: float = 0
    duplicate_pct: float = 0
    direction: Literal["to", "from", "both"] = "to"


class FaultIn(BaseModel):
    kind: Literal["link_down", "isolate", "block", "netem", "deauth", "ban", "ap_down"]
    target: TargetIn
    flow: Literal["rtp_in", "sip_in", "rtp_out", "all_in", "all_out", "blackout"] | None = None
    loss: int = 100
    netem: NetemIn | None = None
    port: int | None = None
    ban_s: int | None = None
    hold_s: int | None = None

    def to_domain(self) -> FaultRequest:
        n = self.netem
        return FaultRequest(
            self.kind,
            TargetRef(self.target.mac, self.target.ip),
            self.flow,
            self.loss,
            NetemParams(
                n.delay_ms,
                n.jitter_ms,
                n.distribution,
                n.loss_pct,
                n.reorder_pct,
                n.duplicate_pct,
                n.direction,
            )
            if n is not None
            else None,
            self.port,
            self.ban_s,
            self.hold_s,
        )


class FaultApplyIn(FaultIn, Digest):
    pass


class ClearIn(BaseModel):
    ids: list[str] | None = None  # None: clear everything


class ClearApplyIn(ClearIn, Digest):
    pass


class CaptureIn(BaseModel):
    device: str
    filter: str = ""
    duration_s: int = 60
    output: Literal["file", "wireshark"] = "file"


class CaptureDevicesOut(BaseModel):
    devices: list[str]
    wireshark: bool


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/faults")
async def faults_state(router_id: str, ctx: Ctx) -> FaultsState:
    return await ctx.faults.state(_known(ctx, router_id))


@router.post("/faults/preview")
async def fault_preview(router_id: str, body: FaultIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.faults.plan_fault(_known(ctx, router_id), body.to_domain()))


@router.post("/faults/apply")
async def fault_apply(router_id: str, body: FaultApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.faults.apply_fault(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/faults/clear/preview")
async def clear_preview(router_id: str, body: ClearIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.faults.plan_clear(_known(ctx, router_id), body.ids))


@router.post("/faults/clear/apply")
async def clear_apply(router_id: str, body: ClearApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.faults.apply_clear(_known(ctx, router_id), body.ids, body.digest)


@router.get("/captures")
async def captures(router_id: str, ctx: Ctx) -> list[CaptureView]:
    return ctx.captures.list(_known(ctx, router_id))


@router.get("/captures/devices")
async def capture_devices(router_id: str, ctx: Ctx) -> CaptureDevicesOut:
    devices = await ctx.captures.devices(_known(ctx, router_id))
    return CaptureDevicesOut(devices=devices, wireshark=ctx.captures.wireshark_available())


@router.post("/captures")
async def capture_start(router_id: str, body: CaptureIn, ctx: Ctx) -> CaptureView:
    req = CaptureRequest(body.device, body.filter, body.duration_s, body.output)
    return await ctx.captures.start(_known(ctx, router_id), req)


@router.post("/captures/{capture_id}/stop")
async def capture_stop(router_id: str, capture_id: str, ctx: Ctx) -> CaptureView:
    _known(ctx, router_id)
    return await ctx.captures.stop(capture_id)
