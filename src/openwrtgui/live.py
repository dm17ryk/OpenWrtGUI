"""Live hub: fans out guard, status and update messages to every open /ws/live connection."""

from __future__ import annotations

import asyncio
from typing import Any

QUEUE_SIZE = 100

Message = dict[str, Any]


class LiveHub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Message]] = set()
        self._guard: Message | None = None
        self._update: Message | None = None
        self._routers: dict[str, Message] = {}

    def subscribe(self) -> asyncio.Queue[Message]:
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Message]) -> None:
        self._queues.discard(q)

    def publish(self, msg: Message) -> None:
        kind = msg.get("type")
        if kind == "guard":
            self._guard = msg
        elif kind == "update":
            self._update = msg
        elif "router" in msg:
            self._routers[str(msg["router"])] = msg
        for q in self._queues:
            if q.full():
                q.get_nowait()
            q.put_nowait(msg)

    def snapshot(self) -> list[Message]:
        head = [m for m in (self._guard, self._update) if m is not None]
        return head + [self._routers[r] for r in sorted(self._routers)]
