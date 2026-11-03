"""Shared request plumbing: the app context and the per-launch token."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, WebSocket

from openwrtgui.context import AppContext

WS_BAD_TOKEN = 4401
WS_BAD_ORIGIN = 4403
WS_NOT_FOUND = 4404


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def require_token(request: Request) -> None:
    ctx = get_ctx(request)
    header = request.headers.get("authorization", "")
    if not secrets.compare_digest(header, f"Bearer {ctx.token}"):
        raise HTTPException(status_code=401, detail="Missing or wrong token")


def allowed_origins(ctx: AppContext) -> set[str]:
    return {f"http://127.0.0.1:{ctx.port}", f"http://localhost:{ctx.port}"}


async def ws_accept(ws: WebSocket) -> AppContext | None:
    """Check token and origin; close with a 44xx code and return None when refused."""
    ctx: AppContext = ws.app.state.ctx
    token = ws.query_params.get("t", "")
    origin = ws.headers.get("origin")
    if not secrets.compare_digest(token, ctx.token):
        await ws.close(code=WS_BAD_TOKEN)
        return None
    if origin is not None and origin not in allowed_origins(ctx):
        await ws.close(code=WS_BAD_ORIGIN)
        return None
    await ws.accept()
    return ctx
