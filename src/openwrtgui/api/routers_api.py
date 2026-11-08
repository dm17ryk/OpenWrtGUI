"""Routers the app knows: list, detail (with self-description), probe again, remove."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import Ok, RouterDetail, RouterItem
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


@router.delete("/{router_id}")
async def remove_router(router_id: str, ctx: Ctx) -> Ok:
    _record(ctx, router_id)
    ctx.routers.remove(router_id)
    await ctx.pool.drop(router_id)
    ctx.statuses.pop(router_id, None)
    ctx.descriptions.pop(router_id, None)
    ctx.discovery.summaries.pop(router_id, None)
    ctx.guard.forget_router(router_id)
    return Ok()
