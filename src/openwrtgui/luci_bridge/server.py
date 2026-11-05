"""A small HTTP server on a random loopback port, inside the app's own event loop."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Generator

import uvicorn
from starlette.types import ASGIApp

STARTUP_TIMEOUT_S = 10.0


class _QuietServer(uvicorn.Server):
    """Ctrl+C and SIGTERM belong to the app's own server; a bridge must not take them over."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


async def serve(app: ASGIApp) -> tuple[int, Callable[[], Awaitable[None]]]:
    """Serve `app` on 127.0.0.1:<random>; returns the port and a coroutine function that stops it."""
    server = _QuietServer(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    waited = 0.0
    while not server.started:
        if task.done():
            task.result()  # raises the reason it could not start
            raise OSError("the loopback server stopped before it started")
        if waited > STARTUP_TIMEOUT_S:
            server.should_exit = True
            raise OSError("the loopback server did not start")
        await asyncio.sleep(0.01)
        waited += 0.01
    port = int(server.servers[0].sockets[0].getsockname()[1])

    async def stop() -> None:
        server.should_exit = True
        await asyncio.gather(task, return_exceptions=True)

    return port, stop
