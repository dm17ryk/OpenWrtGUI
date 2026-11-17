"""Routers the app knows: list, detail (with self-description), probe again, remove."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import Ok, RouterDetail, RouterItem
from openwrtgui.busy import RouterBusy
from openwrtgui.context import AppContext
from openwrtgui.probe.describe import DescriptionSummary, describe_router, summarize
from openwrtgui.store.routers import RouterRecord

router = APIRouter(prefix="/api/routers", dependencies=[Depends(require_token)], tags=["routers"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _record(ctx: AppContext, router_id: str) -> RouterRecord:
    rec = ctx.routers.get(router_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return rec


async def _describe(ctx: AppContext, rec: RouterRecord) -> DescriptionSummary:
    transport = await ctx.pool.get(rec)
    desc = await describe_router(transport)
    ctx.descriptions[rec.id] = desc
    return summarize(desc)


@router.get("")
async def list_routers(ctx: Ctx) -> list[RouterItem]:
    return [
        RouterItem(
            record=r,
            health=ctx.pool.health(r.id),
            status=ctx.statuses.get(r.id),
            summary=summarize(d) if (d := ctx.descriptions.get(r.id)) else None,
            discovery=ctx.discovery.summaries.get(r.id),
        )
        for r in ctx.routers.list()
    ]


@router.get("/{router_id}")
async def router_detail(router_id: str, ctx: Ctx) -> RouterDetail:
    rec = _record(ctx, router_id)
    desc = ctx.descriptions.get(rec.id)
    summary = summarize(desc) if desc else None
    if summary is None and rec.auth == "key":
        summary = await _describe(ctx, rec)
    return RouterDetail(
        record=rec, health=ctx.pool.health(rec.id), status=ctx.statuses.get(rec.id), summary=summary
    )


@router.post("/{router_id}/describe")
async def describe_again(router_id: str, ctx: Ctx) -> DescriptionSummary:
    return await _describe(ctx, _record(ctx, router_id))


def _running_on(ctx: AppContext, router_id: str) -> list[str]:
    """What of the app runs on the router: removing it would orphan that (#77 minor 10, D4). Armed faults come
    from the last status read; with none, they are not known and do not block."""
    found: list[str] = []
    status = ctx.statuses.get(router_id)
    if status is not None and status.faults_armed:
        n = status.faults_armed
        found.append(f"{n} fault{'s' if n != 1 else ''} armed")
    pending = [p.radio for p in ctx.steps.pending() if p.router_id == router_id]
    found += [f"a step-through restore waits on {radio}" for radio in pending]
    if (step := ctx.steps.busy(router_id)) is not None:
        found.append(step[:1].lower() + step[1:])
    if ctx.flash.running(router_id):
        found.append("a flash runs")
    if (capture := ctx.captures.running_on(router_id)) is not None:
        found.append(capture)
    return found


@router.delete("/{router_id}")
async def remove_router(router_id: str, ctx: Ctx) -> Ok:
    rec = _record(ctx, router_id)
    if found := _running_on(ctx, router_id):
        raise RouterBusy(f"{rec.name} is not removed: {'; '.join(found)}. Stop or clear them first.")
    ctx.routers.remove(router_id)
    await ctx.pool.drop(router_id)
    ctx.statuses.pop(router_id, None)
    ctx.descriptions.pop(router_id, None)
    ctx.discovery.summaries.pop(router_id, None)
    ctx.guard.forget_router(router_id)
    return Ok()
