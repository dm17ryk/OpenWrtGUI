"""The System screen's endpoints (spec 7.11, v0.6b plan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.system.service import Connections, TimeZones
from openwrtgui.system.services import ServiceRow
from openwrtgui.system.state import LogEntry, LogKind, ProcessList, SystemOverview

router = APIRouter(
    prefix="/api/routers/{router_id}/system", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def overview(router_id: str, ctx: Ctx) -> SystemOverview:
    return await ctx.system.overview(_known(ctx, router_id))


@router.get("/logs")
async def logs(router_id: str, ctx: Ctx, kind: LogKind = "system", lines: int = 100) -> list[LogEntry]:
    """`lines` is 100, 500 or 2000 (anything else: 422 from the service)."""
    return await ctx.system.logs(_known(ctx, router_id), kind, lines)  # type: ignore[arg-type]


@router.get("/processes")
async def processes(router_id: str, ctx: Ctx) -> ProcessList:
    return await ctx.system.processes(_known(ctx, router_id))


@router.get("/services")
async def services(router_id: str, ctx: Ctx) -> list[ServiceRow]:
    return await ctx.system.services(_known(ctx, router_id))


@router.get("/connections")
async def connections(router_id: str, ctx: Ctx) -> Connections:
    return await ctx.system.connections(_known(ctx, router_id))


@router.get("/timezones")
async def timezones(router_id: str, ctx: Ctx) -> TimeZones:
    return await ctx.system.timezones(_known(ctx, router_id))
