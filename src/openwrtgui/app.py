"""FastAPI app factory: API, WebSockets, the built UI, and the background loops."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from openwrtgui.api import (
    errors,
    faults_api,
    fw_api,
    luci_api,
    misc_api,
    net_api,
    onboard_api,
    ports_api,
    routers_api,
    update_api,
    wifi_api,
    ws_api,
)
from openwrtgui.context import AppContext
from openwrtgui.version import APP_VERSION

log = logging.getLogger(__name__)
UPDATE_LOOP_S = 3600.0
LUCI_TICK_S = 2.0


async def _luci_loop(ctx: AppContext, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await ctx.luci.tick()
        except Exception:
            log.exception("LuCI bridge tick failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), LUCI_TICK_S)


async def _update_loop(ctx: AppContext, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await ctx.updater.check()
        except Exception:
            log.exception("update check failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), UPDATE_LOOP_S)


def create_app(ctx: AppContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(ctx.poller.run(stop)),
            asyncio.create_task(_update_loop(ctx, stop)),
            asyncio.create_task(_luci_loop(ctx, stop)),
        ]
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            ctx.rf.close_all()
            await ctx.luci.close_all()
            await ctx.pool.close_all()

    app = FastAPI(title="OpenWrtGUI", version=APP_VERSION, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    errors.install(app)
    modules = (
        misc_api,
        routers_api,
        onboard_api,
        update_api,
        wifi_api,
        luci_api,
        net_api,
        ports_api,
        fw_api,
        faults_api,
    )
    for module in modules:
        app.include_router(module.router)
    app.include_router(misc_api.public)
    app.include_router(ws_api.router)
    if ctx.web_dir is not None and ctx.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=ctx.web_dir, html=True), name="web")
    return app
