"""Add-router wizard over HTTP. Passwords pass straight through to the router, never stored."""

from __future__ import annotations

from collections.abc import Awaitable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import Ok, Preview
from openwrtgui.context import AppContext
from openwrtgui.onboard.wizard import SessionView
from openwrtgui.store.routers import RouterRecord

router = APIRouter(prefix="/api/onboard", dependencies=[Depends(require_token)], tags=["onboard"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


class StartIn(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)


class TrustIn(BaseModel):
    fingerprint: str


class LoginIn(BaseModel):
    password: str | None = None
    key_path: str | None = None
    username: str = Field(default="root", max_length=32)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1)


class FinishIn(BaseModel):
    name: str
    port_labels: dict[int, str] = {}


async def _session[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="This wizard session has ended; start again") from exc


@router.post("")
async def start(body: StartIn, ctx: Ctx) -> SessionView:
    return await ctx.onboard.start(body.host.strip(), body.port)


@router.post("/{sid}/trust")
async def trust(sid: str, body: TrustIn, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.trust(sid, body.fingerprint))


@router.post("/{sid}/auto-login")
async def auto_login(sid: str, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.auto_login(sid))


@router.post("/{sid}/login")
async def login(sid: str, body: LoginIn, ctx: Ctx) -> SessionView:
    key_path = Path(body.key_path) if body.key_path else None
    return await _session(
        ctx.onboard.login(sid, password=body.password, key_path=key_path, username=body.username)
    )


@router.get("/{sid}/install-key/preview")
async def install_preview(sid: str, ctx: Ctx) -> Preview:
    try:
        return Preview(commands=ctx.onboard.install_key_preview(sid))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="This wizard session has ended; start again") from exc


@router.post("/{sid}/install-key")
async def install_key(sid: str, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.install_key(sid))


@router.post("/{sid}/set-password")
async def set_password(sid: str, body: PasswordIn, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.set_password(sid, body.password))


@router.post("/{sid}/verify")
async def verify(sid: str, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.verify_key(sid))


@router.post("/{sid}/identify")
async def identify(sid: str, ctx: Ctx) -> SessionView:
    return await _session(ctx.onboard.identify(sid))


@router.post("/{sid}/finish")
async def finish(sid: str, body: FinishIn, ctx: Ctx) -> RouterRecord:
    return await _session(ctx.onboard.finish(sid, body.name, body.port_labels))


@router.delete("/{sid}")
async def cancel(sid: str, ctx: Ctx) -> Ok:
    await ctx.onboard.cancel(sid)
    return Ok()
