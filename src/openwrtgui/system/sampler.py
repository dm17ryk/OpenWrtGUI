"""The System screen's live charts (v0.6b plan D3): one read of load, interface counters and the connection
count every 3 s per router, only while a client watches. A read with no answer is a missed sample."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from openwrtgui.store.routers import RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.parse import LiveSample, parse_live, rates
from openwrtgui.transport.base import TransportError
from openwrtgui.transport.pool import ConnectionPool

log = logging.getLogger(__name__)

QUEUE_SIZE = 30
INTERVAL_S = 3.0
NO_ANSWER = "No answer from the router"

Message = dict[str, Any]


class SystemSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    t: float
    load1: float | None
    load5: float | None
    load15: float | None
    connections: int | None
    rates: dict[str, tuple[float, float]]  # interface -> (rx, tx) bytes per second since the last sample


class SystemSampler:
    def __init__(
        self,
        router_id: str,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        interval_s: float = INTERVAL_S,
        busy: Callable[[str], str | None] = lambda router_id: None,
    ) -> None:
        self._busy = busy  # a reboot, restore or reset holds the router: say so, do not wait in pool.get
        self.router_id = router_id
        self._pool = pool
        self._routers = routers
        self._clock = clock
        self._sleep = sleep
        self._interval_s = interval_s
        self._subs: set[asyncio.Queue[Message]] = set()
        self._task: asyncio.Task[None] | None = None
        self._last: LiveSample | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subs.add(queue)
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._loop())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self._subs.discard(queue)
        if not self._subs:
            self.stop()

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _publish(self, msg: Message) -> None:
        for queue in list(self._subs):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(msg)

    async def _loop(self) -> None:
        while True:
            try:
                msg = await self.tick()
            except Exception as exc:  # odd output must not freeze the charts: say so, keep sampling
                log.exception("System sample of %s failed", self.router_id)
                msg = {"type": "system-idle", "reason": f"Sampling failed: {exc}"}
            self._publish(msg)
            await self._sleep(self._interval_s)

    async def tick(self) -> Message:
        """One sample, or the reason there is none. Background read: not audited."""
        rec = self._routers.get(self.router_id)
        if rec is None:
            return {"type": "system-idle", "reason": f"{self.router_id} was removed"}
        if (why := self._busy(self.router_id)) is not None:
            return {"type": "system-idle", "reason": why}
        try:
            t = await self._pool.get(rec)
            result = await t.run(s.LIVE)
        except TransportError as exc:
            return {"type": "system-idle", "reason": str(exc)}
        if not result.stdout.strip():  # the count may be missing (no conntrack) and still give a sample
            return {"type": "system-idle", "reason": NO_ANSWER}
        now = parse_live(result.stdout, self._clock().timestamp())
        since = rates(self._last, now) if self._last is not None else {}
        self._last = now
        sample = SystemSample(
            t=now.t,
            load1=now.load1,
            load5=now.load5,
            load15=now.load15,
            connections=now.connections,
            rates=since,
        )
        return {"type": "system", "sample": sample}


class SystemHub:
    """One sampler per router, shared by every client watching it."""

    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        busy: Callable[[str], str | None] = lambda router_id: None,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._busy = busy
        self._samplers: dict[str, SystemSampler] = {}

    def sampler(self, router_id: str) -> SystemSampler:
        if router_id not in self._samplers:
            self._samplers[router_id] = SystemSampler(
                router_id, pool=self._pool, routers=self._routers, busy=self._busy
            )
        return self._samplers[router_id]

    def close_all(self) -> None:
        for sampler in self._samplers.values():
            sampler.stop()
