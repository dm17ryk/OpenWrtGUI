"""The monitor interface the app adds on a radio, shared by its users (v0.7 plan D11).

The beacon check of a Wi-Fi Apply, Capture on mon0 and frame analysis all listen on `owgmon0`. The first
holder adds it, the last one removes it, and nobody removes it while another holder uses it. A Wi-Fi reload
removes every interface on the phy, so a holder checks that it is still there and adds it again.

The leases never take the router's write lock: the beacon check already holds it, and asyncio's locks are not
reentrant. Callers that do not hold it (capture, frame analysis) take it around `acquire`, `ensure` and
`release`. `generation` moves on every add, so a holder sees that someone else put the monitor back.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

from openwrtgui.transport.base import CommandResult, Transport, TransportError

MONITOR = "owgmon0"
DEL = f"iw dev {MONITOR} del"
INFO = f"iw dev {MONITOR} info"

RunFn = Callable[[str, bool], Awaitable[CommandResult]]  # (command, require_guard): the caller's audited run


def add_command(phy: str, *, clear_leftover: bool) -> str:
    """With clear_leftover, the command the beacon check and capture always sent (recordings match it)."""
    head = f"iw dev {MONITOR} del 2>/dev/null; " if clear_leftover else ""
    return head + f"iw phy {phy} interface add {MONITOR} type monitor && ip link set {MONITOR} up"


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


class MonitorLeases:
    def __init__(self) -> None:
        self._holders: dict[str, list[str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}

    def _lock(self, router_id: str) -> asyncio.Lock:
        return self._locks.setdefault(router_id, asyncio.Lock())

    def holders(self, router_id: str) -> tuple[str, ...]:
        return tuple(self._holders.get(router_id, ()))

    def generation(self, router_id: str) -> int:
        """Counts the adds: a holder that set something on the interface (frame analysis's flags) sets it
        again when this moved, whoever added the monitor again after a reload."""
        return self._generations.get(router_id, 0)

    def _added(self, router_id: str) -> None:
        self._generations[router_id] = self.generation(router_id) + 1

    async def acquire(self, router_id: str, holder: str, phy: str, t: Transport, run: RunFn) -> None:
        """Add the monitor for the first holder, or check it is there for a later one. ValueError when the
        router refuses it; then this holder is not registered."""
        async with self._lock(router_id):
            if self._holders.get(router_id):
                await self._ensure(router_id, phy, t, run)
            else:
                try:
                    done = await run(add_command(phy, clear_leftover=True), True)
                except TransportError:  # the router may have made it before the connection dropped
                    with contextlib.suppress(TransportError):
                        await run(DEL, False)
                    raise
                if not done.ok:
                    raise ValueError(_reason(done))
                self._added(router_id)
            self._holders.setdefault(router_id, []).append(holder)

    async def release(self, router_id: str, holder: str, run: RunFn, t: Transport) -> CommandResult | None:
        """Drop one holder; the last one removes the monitor (allowed during a run: it only undoes what the
        app made). The removal's result, or None while other holders remain. A refused removal is checked
        (gone already, say after a reload, counts as removed) and tried once more; a result that is still not
        ok means the monitor is left on the radio, and the caller says so."""
        async with self._lock(router_id):
            held = self._holders.get(router_id, [])
            if holder in held:
                held.remove(holder)
            if held:
                return None
            self._holders.pop(router_id, None)
            done = await run(DEL, False)
            if done.ok:
                return done
            if not (await t.run(INFO)).ok:
                return CommandResult(DEL, "", "", 0)
            return await run(DEL, False)

    async def ensure(self, router_id: str, phy: str, t: Transport, run: RunFn) -> bool:
        """True when the monitor was gone (a Wi-Fi reload) and was added again."""
        async with self._lock(router_id):
            return await self._ensure(router_id, phy, t, run)

    async def _ensure(self, router_id: str, phy: str, t: Transport, run: RunFn) -> bool:
        if (await t.run(INFO)).ok:
            return False
        done = await run(add_command(phy, clear_leftover=False), True)
        if not done.ok:
            raise ValueError(_reason(done))
        self._added(router_id)
        return True

    @contextlib.asynccontextmanager
    async def hold(
        self, router_id: str, holder: str, phy: str, t: Transport, run: RunFn
    ) -> AsyncIterator[None]:
        await self.acquire(router_id, holder, phy, t, run)
        try:
            yield
        finally:
            await self.release(router_id, holder, run, t)
