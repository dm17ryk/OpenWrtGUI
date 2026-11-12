"""Update check, skip, install and reinstall-previous."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import UpdateOut
from openwrtgui.context import AppContext

router = APIRouter(prefix="/api/update", dependencies=[Depends(require_token)], tags=["update"])
Ctx = Annotated[AppContext, Depends(get_ctx)]
STOP_LIMIT_S = 120.0


class VersionIn(BaseModel):
    version: str


class InstallIn(VersionIn):
    force: bool = False


class ReinstallIn(BaseModel):
    force: bool = False


def _out(ctx: AppContext) -> UpdateOut:
    return UpdateOut.of(ctx.updater.status(), ctx.updater.previous_installer() is not None)


async def _close_terminals_and_quit(ctx: AppContext, command: list[str]) -> None:
    for session in list(ctx.terminals):
        await session.close()
    ctx.terminals.clear()
    ctx.exit_command = command
    ctx.quit_event.set()


@router.get("")
async def status(ctx: Ctx) -> UpdateOut:
    return _out(ctx)


@router.post("/check")
async def check(ctx: Ctx) -> UpdateOut:
    await ctx.updater.check(force=True)
    return _out(ctx)


@router.post("/skip")
async def skip(body: VersionIn, ctx: Ctx) -> UpdateOut:
    ctx.updater.skip(body.version)
    return _out(ctx)


def _live(ctx: AppContext) -> list[str]:
    """Work the update would stop (spec 9.3): step-throughs, captures and frame analysis."""
    return [*ctx.steps.live(), *ctx.captures.live(), *ctx.rf.live_frames()]


async def _stop_live(ctx: AppContext) -> None:
    """Each step-through restores its radio first (v0.7 plan D15); a restore that fails keeps its file."""
    await ctx.steps.stop_all(limit_s=STOP_LIMIT_S)
    await ctx.captures.stop_all()
    await ctx.rf.stop_frames()


def _ask_first(ctx: AppContext, force: bool) -> JSONResponse | None:
    """The 409 that asks before live work or terminals are stopped; None when there is nothing to ask."""
    live = _live(ctx)
    if (ctx.terminals or live) and not force:
        detail = "Live work is running" if live else "Terminal sessions are open"
        return JSONResponse(
            status_code=409,
            content={"detail": detail, "open_terminals": len(ctx.terminals), "live": live},
        )
    return None


@router.post("/install", status_code=202)
async def install(body: InstallIn, ctx: Ctx) -> JSONResponse:
    if (asked := _ask_first(ctx, body.force)) is not None:
        return asked
    # downloaded and verified first: nothing is stopped when that fails
    command = await ctx.updater.install(body.version)
    await _stop_live(ctx)
    await _close_terminals_and_quit(ctx, command)
    return JSONResponse(status_code=202, content={"status": "installing", "version": body.version})


@router.post("/reinstall-previous", status_code=202)
async def reinstall_previous(ctx: Ctx, body: ReinstallIn | None = None) -> JSONResponse:
    """The same question and the same stop as an update (PR #59 review)."""
    command = ctx.updater.reinstall_command()
    if command is None:
        raise HTTPException(status_code=404, detail="No previous installer is kept")
    if (asked := _ask_first(ctx, body is not None and body.force)) is not None:
        return asked
    await _stop_live(ctx)
    await _close_terminals_and_quit(ctx, command)
    return JSONResponse(status_code=202, content={"status": "installing"})
