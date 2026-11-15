"""Waiting for a router to settle before an as-found check (AP2 window 2026-11-15)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def settled[T](
    read: Callable[[], Awaitable[T]],
    want: T,
    *,
    tries: int = 15,
    pause_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Reads until a read equals `want` or `tries` reads were made; returns the last read."""
    got = await read()
    for _ in range(tries - 1):
        if got == want:
            break
        await sleep(pause_s)
        got = await read()
    return got
