"""The live LTE signal (v0.6a plan D1): one read every 10 s per router, only while a client watches. A read
that gets no answer is a missed sample ("No answer from the modem"), never a state change."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from openwrtgui.lte import commands as c
from openwrtgui.lte.parse import parse_serving, parse_signal
from openwrtgui.store.routers import RouterStore
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

log = logging.getLogger(__name__)

QUEUE_SIZE = 30
INTERVAL_S = 10.0
LOCATE_EVERY_TICKS = 30  # look the modem device up again every 5 minutes
NO_ANSWER = "No answer from the modem"
NO_LTE = "This router has no LTE interface"

Message = dict[str, Any]
Locate = Callable[[str], Awaitable[str | None]]


class LteSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    t: float
    rssi: float | None
    rsrp: float | None
    rsrq: float | None
    snr: float | None
    registration: str | None
    radio: str | None


async def _stdout(t: Transport, command: str) -> str:
    result = await t.run(command)
    return result.stdout if result.ok else ""


class LteSampler:
    def __init__(
        self,
        router_id: str,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        locate: Locate,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        interval_s: float = INTERVAL_S,
    ) -> None:
        self.router_id = router_id
        self._pool = pool
        self._routers = routers
        self._locate = locate
        self._clock = clock
        self._sleep = sleep
        self._interval_s = interval_s
        self._subs: set[asyncio.Queue[Message]] = set()
        self._task: asyncio.Task[None] | None = None
        self._device: str | None = None
        self._ticks = 0

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
            except Exception as exc:  # odd modem output must not freeze the screen: say so, keep sampling
                log.exception("LTE sample of %s failed", self.router_id)
                msg = {"type": "lte-idle", "reason": f"LTE sampling failed: {exc}"}
            self._publish(msg)
            await self._sleep(self._interval_s)

    async def tick(self) -> Message:
        """One sample, or the reason there is none. Background read: not audited."""
        rec = self._routers.get(self.router_id)
        if rec is None:
            return {"type": "lte-idle", "reason": f"{self.router_id} was removed"}
        try:
            if self._device is None or self._ticks % LOCATE_EVERY_TICKS == 0:
                self._device = await self._locate(self.router_id)
            self._ticks += 1
            if self._device is None:
                return {"type": "lte-idle", "reason": NO_LTE}
            t = await self._pool.get(rec)
            serving = parse_serving(await _stdout(t, c.SERVING(self._device)))
            signal = parse_signal(await _stdout(t, c.SIGNAL(self._device)))
        except TransportError as exc:
            return {"type": "lte-idle", "reason": str(exc)}
        if serving is None and signal is None:
            return {"type": "lte-idle", "reason": NO_ANSWER}
        sample = LteSample(
            t=self._clock().timestamp(),
            rssi=signal.rssi if signal else None,
            rsrp=signal.rsrp if signal else None,
            rsrq=signal.rsrq if signal else None,
            snr=signal.snr if signal else None,
            registration=serving.registration if serving else None,
            radio=serving.radio if serving else None,
        )
        return {"type": "lte", "sample": sample}


class LteHub:
    """One sampler per router, shared by every client watching it."""

    def __init__(self, *, pool: ConnectionPool, routers: RouterStore, locate: Locate) -> None:
        self._pool = pool
        self._routers = routers
        self._locate = locate
        self._samplers: dict[str, LteSampler] = {}

    def sampler(self, router_id: str) -> LteSampler:
        if router_id not in self._samplers:
            self._samplers[router_id] = LteSampler(
                router_id, pool=self._pool, routers=self._routers, locate=self._locate
            )
        return self._samplers[router_id]

    def close_all(self) -> None:
        for sampler in self._samplers.values():
            sampler.stop()
