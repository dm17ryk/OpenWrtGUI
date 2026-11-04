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


class VersionIn(BaseModel):
    version: str


class InstallIn(VersionIn):
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


@router.post("/install", status_code=202)
async def install(body: InstallIn, ctx: Ctx) -> JSONResponse:
    if ctx.terminals and not body.force:
        return JSONResponse(
            status_code=409,
            content={"detail": "Terminal sessions are open", "open_terminals": len(ctx.terminals)},
        )
    command = await ctx.updater.install(body.version)
    await _close_terminals_and_quit(ctx, command)
    return JSONResponse(status_code=202, content={"status": "installing", "version": body.version})


@router.post("/reinstall-previous", status_code=202)
async def reinstall_previous(ctx: Ctx) -> JSONResponse:
    command = ctx.updater.reinstall_command()
    if command is None:
        raise HTTPException(status_code=404, detail="No previous installer is kept")
    await _close_terminals_and_quit(ctx, command)
    return JSONResponse(status_code=202, content={"status": "installing"})
