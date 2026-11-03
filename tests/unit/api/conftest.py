from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from apiconst import BASE, PORT, TOKEN

from openwrtgui.app import create_app
from openwrtgui.context import AppContext, build_context
from openwrtgui.paths import DataDir
from openwrtgui.store import keys as keys_module

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"


@pytest.fixture(autouse=True)
def _no_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    yield build_context(
        DataDir.at(tmp_path / "data"), token=TOKEN, port=PORT, simulator=SIM_DIR, web_dir=None
    )


@pytest.fixture
def ctx_guard_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
    c = build_context(DataDir.at(tmp_path / "data"), token=TOKEN, port=PORT, simulator=SIM_DIR, web_dir=None)
    c.guard.check_local()
    yield c


def _client(c: AppContext, token: str | None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url=BASE, headers=headers)


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(ctx, None) as c:
        yield c


@pytest.fixture
async def authed(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(ctx, TOKEN) as c:
        yield c


@pytest.fixture
async def authed_guard_live(ctx_guard_live: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(ctx_guard_live, TOKEN) as c:
        yield c
