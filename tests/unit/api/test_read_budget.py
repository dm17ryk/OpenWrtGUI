"""The SSH command budget of the reads v1.0c speeds up (plan, Task 1). A task that speeds a read lowers its
row first, sees it fail, then makes the read meet it; no row may grow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from apiconst import BASE, PORT, TOKEN
from readcount import at_exchanges, commands_of, count_read

from openwrtgui.app import create_app
from openwrtgui.context import AppContext, build_context
from openwrtgui.paths import DataDir

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 16, 9, 0)

# SSH commands of a warm read at 108a89e (2026-11-16); a task that speeds a read lowers its row first.
WARM = {
    ("ap1", "/api/routers/ap1/lte"): 11,
    ("ap1", "/api/routers/ap1/faults"): 19,
    ("ap4", "/api/routers/ap4/firewall/iptables"): 1,
    ("ap1", "/api/routers/ap1/firewall"): 9,
    ("ap1", "/api/routers/ap1/network"): 4,
    ("ap1", "/api/routers/ap1/wifi"): 6,
    ("ap1", "/api/routers/ap1/ports"): 10,
    ("ap1", "/api/routers/ap1/system/access"): 9,
}
AT_WARM = {("ap1", "/api/routers/ap1/lte"): 1}
HELP_PREVIEW = 12  # Discovery Run --help preview on ap1 with the mini image's profile, the router described
POLL_TICK = 7  # one status tick on ap1, after the first


@pytest.fixture
def seeded_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    monkeypatch.setenv("OPENWRTGUI_SIM_SEED", "ap4,ap5")
    data = DataDir.at(tmp_path / "data")
    yield build_context(data, token=TOKEN, port=PORT, simulator=SIM_DIR, web_dir=None)


@pytest.fixture
async def seeded(seeded_ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(seeded_ctx))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(transport=transport, base_url=BASE, headers=headers) as c:
        yield c


@pytest.mark.parametrize("key", list(WARM))
async def test_a_warm_read_stays_within_its_budget(
    seeded: httpx.AsyncClient, seeded_ctx: AppContext, key: tuple[str, str]
) -> None:
    router, path = key
    await seeded.get(path)
    sent = await count_read(seeded, seeded_ctx, router, "GET", path)
    assert len(sent) <= WARM[key], sent


@pytest.mark.parametrize("key", list(AT_WARM))
async def test_a_warm_read_asks_the_modem_within_its_budget(
    seeded: httpx.AsyncClient, seeded_ctx: AppContext, key: tuple[str, str]
) -> None:
    router, path = key
    await seeded.get(path)
    sent = await count_read(seeded, seeded_ctx, router, "GET", path)
    assert at_exchanges(sent) <= AT_WARM[key], sent


async def test_a_run_help_preview_stays_within_its_budget(
    seeded: httpx.AsyncClient, seeded_ctx: AppContext
) -> None:
    seeded_ctx.profiles.import_image(MINI.read_bytes(), "mini-r35692.bin", NOW)
    await seeded.get("/api/routers/ap1")  # describes the router, as the poller's first tick does
    sent = await count_read(
        seeded,
        seeded_ctx,
        "ap1",
        "POST",
        "/api/routers/ap1/discovery/help/preview",
        {"path": "/usr/bin/dwr921-at-probe"},
    )
    assert len(sent) <= HELP_PREVIEW, sent


async def test_a_status_tick_stays_within_its_budget(seeded_ctx: AppContext) -> None:
    await seeded_ctx.poller.poll_all()
    before = len(await commands_of(seeded_ctx, "ap1"))
    await seeded_ctx.poller.poll_all()
    assert len(await commands_of(seeded_ctx, "ap1")) - before <= POLL_TICK
