"""WebSockets: /ws/live (guard, status, updates), /ws/rf/{router_id} and /ws/terminal/{router_id}."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from openwrtgui.api.deps import WS_NOT_FOUND, ws_accept
from openwrtgui.api.models import wire
from openwrtgui.terminal import TerminalSession
from openwrtgui.transport.base import TransportError

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    ctx = await ws_accept(ws)
    if ctx is None:
        return
    queue = ctx.hub.subscribe()
    has_previous = ctx.updater.previous_installer() is not None
    try:
        await ws.send_json(wire({"type": "guard", "state": ctx.guard.state()}))
        for msg in ctx.hub.snapshot():
            if msg.get("type") != "guard":
                await ws.send_json(wire(msg, has_previous))
        while True:
            await ws.send_json(wire(await queue.get(), has_previous))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        ctx.hub.unsubscribe(queue)


@router.websocket("/ws/rf/{router_id}")
async def rf_live(ws: WebSocket, router_id: str) -> None:
    """RF samples once a second; the client may ask to record to CSV or for a station's rates."""
    ctx = await ws_accept(ws)
    if ctx is None:
        return
    if ctx.routers.get(router_id) is None:
        await ws.close(code=WS_NOT_FOUND)
        return
    sampler = ctx.rf.sampler(router_id, ws.query_params.get("radio", "radio0"))
    queue = sampler.subscribe()

    async def send_samples() -> None:
        while True:
            await ws.send_json(wire(await queue.get()))

    sender = asyncio.create_task(send_samples())
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "record":
                path = sampler.start_recording() if msg.get("on") else sampler.stop_recording()
                await ws.send_json(
                    {"type": "recording", "path": str(path) if path and msg.get("on") else None}
                )
            elif kind == "rates":
                mac = str(msg.get("mac", ""))
                try:
                    await ws.send_json(wire({"type": "rates", "mac": mac, "rows": await sampler.rates(mac)}))
                except (NotImplementedError, TransportError, ValueError) as exc:
                    await ws.send_json({"type": "rates", "mac": mac, "error": str(exc)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        sampler.unsubscribe(queue)


@router.websocket("/ws/lte/{router_id}")
async def lte_live(ws: WebSocket, router_id: str) -> None:
    """The LTE signal every 10 s while the screen is open (v0.6a plan D1)."""
    ctx = await ws_accept(ws)
    if ctx is None:
        return
    if ctx.routers.get(router_id) is None:
        await ws.close(code=WS_NOT_FOUND)
        return
    sampler = ctx.lte_live.sampler(router_id)
    queue = sampler.subscribe()

    async def send_samples() -> None:
        while True:
            await ws.send_json(wire(await queue.get()))

    sender = asyncio.create_task(send_samples())
    try:
        while True:
            await ws.receive_json()  # nothing to ask yet; reading notices the close
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        sampler.unsubscribe(queue)


@router.websocket("/ws/terminal/{router_id}")
async def terminal(ws: WebSocket, router_id: str) -> None:
    ctx = await ws_accept(ws)
    if ctx is None:
        return
    rec = ctx.routers.get(router_id)
    if rec is None:
        await ws.close(code=WS_NOT_FOUND)
        return

    async def emit(msg: dict[str, Any]) -> None:
        await ws.send_json(msg)

    cols = int(ws.query_params.get("cols", "120"))
    rows = int(ws.query_params.get("rows", "32"))
    # Subscribe before opening, then re-sync: a guard change during open() is not missed.
    queue = ctx.hub.subscribe()
    try:
        session = await TerminalSession.open(
            rec, pool=ctx.pool, guard=ctx.guard, audit=ctx.audit, emit=emit, cols=cols, rows=rows
        )
    except TransportError as exc:
        ctx.hub.unsubscribe(queue)
        await ws.send_json({"type": "error", "detail": str(exc)})
        await ws.close()
        return
    ctx.terminals.add(session)
    await session.on_guard(ctx.guard.state())

    async def follow_guard() -> None:
        while True:
            msg = await queue.get()
            if msg.get("type") == "guard":
                await session.on_guard(msg["state"])

    watcher = asyncio.create_task(follow_guard())
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "input":
                await session.input(str(msg.get("data", "")))
            elif kind == "line":
                await session.run_line(str(msg.get("text", "")))
            elif kind == "resize":
                await session.resize(int(msg.get("cols", cols)), int(msg.get("rows", rows)))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except (TransportError, ValueError) as exc:
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await ws.send_json({"type": "error", "detail": str(exc)})
    finally:
        watcher.cancel()
        ctx.hub.unsubscribe(queue)
        ctx.terminals.discard(session)
        await session.close()
