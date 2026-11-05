"""The RF sampler: one read a second per router radio, only while at least one client watches."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from openwrtgui.paths import documents_dir
from openwrtgui.rf.parse import parse_station_dump, parse_survey, split_sections
from openwrtgui.rf.recorder import CsvRecorder
from openwrtgui.rf.sample import RawTick, derive, rf_command
from openwrtgui.store.routers import RouterStore
from openwrtgui.transport.base import TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.parse import parse_iw_dev_info

log = logging.getLogger(__name__)

QUEUE_SIZE = 30
STATUS_EVERY_TICKS = 10  # re-read which interface and phy the radio uses every 10 s
NAMES_EVERY = timedelta(minutes=1)
RATES_NOT_YET = "Rates are read after the AP2 recording (O6)"

Message = dict[str, Any]


class RfSampler:
    def __init__(
        self,
        router_id: str,
        radio: str,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        interval_s: float = 1.0,
        recordings: Path | None = None,
    ) -> None:
        self.router_id = router_id
        self.radio = radio
        self._pool = pool
        self._routers = routers
        self._recordings = recordings
        self._clock = clock
        self._sleep = sleep
        self._interval_s = interval_s
        self._subs: set[asyncio.Queue[Message]] = set()
        self._task: asyncio.Task[None] | None = None
        self._prev: RawTick | None = None
        self._where: tuple[str, str] | None = None  # (ifname, phy)
        self._ticks = 0
        self._names: dict[str, str] = {}
        self._names_at: datetime | None = None
        self._recorder: CsvRecorder | None = None

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
        self.stop_recording()
        self._prev = None

    def _publish(self, msg: Message) -> None:
        for queue in list(self._subs):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(msg)

    async def _loop(self) -> None:
        while True:
            self._publish(await self.tick())
            await self._sleep(self._interval_s)

    async def _locate(self, t: Any) -> tuple[str, str] | None:
        if self._where is None or self._ticks % STATUS_EVERY_TICKS == 0:
            status = (await ubus_call(t, "network.wireless", "status") or {}).get(self.radio, {})
            ifname = next((i["ifname"] for i in status.get("interfaces", []) if i.get("ifname")), None)
            if not status.get("up") or ifname is None:
                self._where = None
                return None
            phyname = await ubus_call(t, "iwinfo", "phyname", {"section": self.radio}) or {}
            self._where = (str(ifname), str(phyname.get("phyname", "phy0")))
        return self._where

    async def _refresh_names(self, t: Any, now: datetime) -> None:
        if self._names_at is not None and now - self._names_at < NAMES_EVERY:
            return
        hints = await ubus_call(t, "luci-rpc", "getHostHints") or {}
        self._names = {mac.lower(): str(h["name"]) for mac, h in hints.items() if h.get("name")}
        self._names_at = now

    async def tick(self) -> Message:
        """One sample (or the reason there is none). Background read: not audited."""
        rec = self._routers.get(self.router_id)
        if rec is None:
            return {"type": "rf-idle", "reason": f"{self.router_id} was removed"}
        try:
            t = await self._pool.get(rec)
            where = await self._locate(t)
            self._ticks += 1
            if where is None:
                self._prev = None
                return {"type": "rf-idle", "reason": f"{self.radio} is parked"}
            ifname, phy = where
            sections = split_sections((await t.run(rf_command(ifname, phy))).stdout)
            now = self._clock()
            await self._refresh_names(t, now)
        except TransportError as exc:
            self._prev, self._where = None, None
            return {"type": "rf-idle", "reason": str(exc)}
        info = parse_iw_dev_info(sections.get("INFO", ""))
        if not info.ifname:
            self._where = None  # the interface went away (a reload): find it again next time
            return {"type": "rf-idle", "reason": f"{self.radio} is restarting"}
        ack = sections.get("ACK", "").strip()
        survey = next((s for s in parse_survey(sections.get("SURVEY", "")) if s.in_use), None)
        raw = RawTick(
            now,
            tuple(parse_station_dump(sections.get("STA", ""))),
            survey,
            int(ack) if ack.isdigit() else None,
            info,
        )
        sample = derive(self._prev, raw, self.router_id, self.radio, self._names)
        self._prev = raw
        if self._recorder is not None:
            self._recorder.write(sample)
        return {"type": "rf", "sample": sample}

    def start_recording(self) -> Path:
        self.stop_recording()
        stamp = self._clock().strftime("%Y%m%d-%H%M%S")
        folder = self._recordings or documents_dir() / "OpenWrtGUI"
        path = folder / f"rf-{self.router_id}-{self.radio}-{stamp}.csv"
        self._recorder = CsvRecorder(path)
        return path

    def stop_recording(self) -> Path | None:
        if self._recorder is None:
            return None
        path = self._recorder.path
        self._recorder.close()
        self._recorder = None
        return path

    async def rates(self, mac: str) -> list[Any]:
        raise NotImplementedError(RATES_NOT_YET)


class RfHub:
    """One sampler per router radio, shared by every client watching it."""

    def __init__(self, *, pool: ConnectionPool, routers: RouterStore, recordings: Path | None = None) -> None:
        self._pool = pool
        self._routers = routers
        self._recordings = recordings  # None: Documents\OpenWrtGUI
        self._samplers: dict[tuple[str, str], RfSampler] = {}

    def sampler(self, router_id: str, radio: str) -> RfSampler:
        key = (router_id, radio)
        if key not in self._samplers:
            self._samplers[key] = RfSampler(
                router_id, radio, pool=self._pool, routers=self._routers, recordings=self._recordings
            )
        return self._samplers[key]

    def close_all(self) -> None:
        for sampler in self._samplers.values():
            sampler.stop()
