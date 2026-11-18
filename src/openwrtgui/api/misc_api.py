"""Bench Guard state, settings, the app key, the audit log, and app-level actions."""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import AppInfo, AppKeyOut, GuardOut, Health, Ok
from openwrtgui.context import AppContext
from openwrtgui.guard.audit import AuditEntry
from openwrtgui.store.settings import Settings
from openwrtgui.version import APP_VERSION

public = APIRouter(tags=["app"])
router = APIRouter(prefix="/api", dependencies=[Depends(require_token)], tags=["app"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


@public.get("/api/health")
async def health(ctx: Ctx) -> Health:
    return Health(status="ok", version=APP_VERSION, mode=ctx.mode)


@router.get("/guard")
async def guard(ctx: Ctx) -> GuardOut:
    return GuardOut.of(ctx.guard.state())


@router.get("/settings")
async def get_settings(ctx: Ctx) -> Settings:
    return ctx.settings.load()


@router.put("/settings")
async def put_settings(body: Settings, ctx: Ctx) -> Settings:
    ctx.settings.save(body)
    ctx.guard.update_watch(body.guard)
    return body


@router.get("/app-key")
async def app_key(ctx: Ctx) -> AppKeyOut:
    nxt = ctx.keys.next
    return AppKeyOut(
        public_line=ctx.keys.current.public_line,
        fingerprint=ctx.keys.current.fingerprint,
        next_fingerprint=nxt.fingerprint if nxt else None,
    )


@router.get("/app-key/public", response_class=PlainTextResponse)
async def app_key_public(ctx: Ctx) -> PlainTextResponse:
    return PlainTextResponse(
        ctx.keys.current.public_line + "\n",
        headers={"Content-Disposition": 'attachment; filename="openwrtgui.pub"'},
    )


@router.get("/audit")
async def audit(
    ctx: Ctx,
    router: str | None = None,
    text: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
) -> list[AuditEntry]:
    return ctx.audit.query(router=router, text=text, since=since, limit=min(limit, 5000))


@router.get("/audit/export", response_class=FileResponse)
async def audit_export(ctx: Ctx) -> FileResponse:
    exports = ctx.data.root / "exports"
    exports.mkdir(exist_ok=True)
    path = ctx.audit.export_zip(exports / f"openwrtgui-audit-{date.today().isoformat()}.zip")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/app/info")
async def app_info(ctx: Ctx) -> AppInfo:
    return AppInfo(
        version=APP_VERSION,
        mode=ctx.mode,
        data_dir=str(ctx.data.root),
        can_install=ctx.updater.status().can_install,
    )


@router.post("/app/open-data-dir")
def open_data_dir(ctx: Ctx) -> Ok:
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        startfile(ctx.data.root)
    else:
        # S603/S607: the desktop's opener on the data folder: fixed argv, no shell
        subprocess.Popen(["xdg-open", str(ctx.data.root)])  # noqa: S603, S607
    return Ok()


@router.post("/app/quit")
async def quit_app(ctx: Ctx) -> Ok:
    ctx.quit_event.set()
    return Ok()
