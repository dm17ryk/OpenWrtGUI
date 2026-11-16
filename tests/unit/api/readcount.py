"""How many SSH commands a request sends: the simulator's connection keeps every command in `calls` (v1.0c)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from openwrtgui.context import AppContext
from openwrtgui.transport.fake import ReplayTransport


async def commands_of(ctx: AppContext, router_id: str) -> list[str]:
    """The live list of commands the pooled connection to router_id has run (the list itself, not a copy)."""
    rec = ctx.routers.get(router_id)
    assert rec is not None, router_id
    t = await ctx.pool.get(rec)
    assert isinstance(t, ReplayTransport)
    return t.calls


async def count_read(
    client: httpx.AsyncClient,
    ctx: AppContext,
    router_id: str,
    method: str,
    path: str,
    json: object | None = None,
) -> list[str]:
    """The commands one request added; the request must answer 200."""
    before = len(await commands_of(ctx, router_id))
    r = await client.request(method, path, json=json)
    assert r.status_code == 200, r.text
    return (await commands_of(ctx, router_id))[before:]


def at_exchanges(sent: Sequence[str]) -> int:
    """The modem exchanges among them: each runs `microcom`, which waits 2 s of silence after the answer."""
    return sum(1 for command in sent if "microcom" in command)
