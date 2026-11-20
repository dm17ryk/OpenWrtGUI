"""The Tools screen's active pages (v1.2b): Throughput, the Traffic generator and Station management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.tools.sessions import SessionView, ToolPlan
from openwrtgui.tools.throughput import ThroughputRequest, ThroughputStart
from openwrtgui.tools.traffic import ListenRequest, ListenStart, SendApply, SendRequest, SendResult

router = APIRouter(
    prefix="/api/routers/{router_id}/tools", dependencies=[Depends(require_token)], tags=["tools"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.post("/throughput/preview")
async def throughput_preview(router_id: str, body: ThroughputRequest, ctx: Ctx) -> ToolPlan:
    return ctx.tools.throughput_plan(_known(ctx, router_id), body)


@router.post("/throughput/start")
async def throughput_start(router_id: str, body: ThroughputStart, ctx: Ctx) -> SessionView:
    req = ThroughputRequest.model_validate(body.model_dump(exclude={"digest"}))
    return await ctx.tools.throughput_start(_known(ctx, router_id), req, body.digest)


@router.post("/traffic/listen/preview")
async def listen_preview(router_id: str, body: ListenRequest, ctx: Ctx) -> ToolPlan:
    return ctx.tools.listen_plan(_known(ctx, router_id), body)


@router.post("/traffic/listen/start")
async def listen_start(router_id: str, body: ListenStart, ctx: Ctx) -> SessionView:
    req = ListenRequest.model_validate(body.model_dump(exclude={"digest"}))
    return await ctx.tools.listen_start(_known(ctx, router_id), req, body.digest)


@router.post("/traffic/send/preview")
async def send_preview(router_id: str, body: SendRequest, ctx: Ctx) -> ToolPlan:
    return ctx.tools.send_plan(_known(ctx, router_id), body)


@router.post("/traffic/send/apply")
async def send_apply(router_id: str, body: SendApply, ctx: Ctx) -> SendResult:
    req = SendRequest.model_validate(body.model_dump(exclude={"digest"}))
    return await ctx.tools.send(_known(ctx, router_id), req, body.digest)


@router.get("/sessions")
async def sessions(router_id: str, ctx: Ctx) -> list[SessionView]:
    return ctx.tool_sessions.list(_known(ctx, router_id))


@router.post("/sessions/{session_id}/stop")
async def stop_session(router_id: str, session_id: str, ctx: Ctx) -> SessionView:
    _known(ctx, router_id)
    try:
        view = ctx.tool_sessions.get(session_id)
    except ValueError:
        view = None
    if view is None or view.router_id != router_id:
        raise HTTPException(status_code=404, detail=f"No tool session {session_id} on {router_id}")
    return await ctx.tool_sessions.stop(session_id)
