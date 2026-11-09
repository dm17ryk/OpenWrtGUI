"""Waiting for a router that restarts (a flash, or the System screen's reboot) to come back, proven by a fresh
uptime: one younger than the time since the restart was armed. Until then the answer is the old system (the
router-side timer has not fired yet) or nothing at all (it is booting)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import HostKeyChanged, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

UPTIME = "cat /proc/uptime"


@dataclass(frozen=True)
class Back[T]:
    uptime_s: float
    elapsed_s: float  # since the restart was armed
    proof: T | None  # what `prove` read once the router was back


async def wait_for_reboot[T](
    pool: ConnectionPool,
    rec: RouterRecord,
    *,
    armed_at: float,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[object]],
    every_s: float = 5.0,
    limit_s: float,
    prove: Callable[[Transport, float], Awaitable[T]] | None = None,
) -> Back[T] | None:
    """Hold the router's connection (nobody else reconnects meanwhile), try every `every_s`, and return once
    the uptime is fresh and `prove` (if any) read what it needs; None after `limit_s`. A changed host key is
    raised at once: waiting would not change it. A read that fails, here or in `prove`, means try again."""
    async with pool.hold(rec.id) as token:
        await pool.drop(rec.id)
        while True:
            await sleep(every_s)
            elapsed = clock() - armed_at
            if elapsed > limit_s:
                return None
            try:
                await pool.drop(rec.id)
                t = await pool.get(rec, token=token)
                uptime = float((await t.run(UPTIME)).stdout.split()[0])
                if uptime >= elapsed:
                    continue  # still the old system
                proof = await prove(t, uptime) if prove is not None else None
            except HostKeyChanged:
                raise
            except (TransportError, ValueError, IndexError):
                continue
            return Back(uptime, elapsed, proof)
