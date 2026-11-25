"""LteService.write_slot (v1.3b E12): one LTE write at a time per router, never queued, refused while Recover
runs; the SIM, SMS and USSD writes and the AT console's writes take it."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from openwrtgui.busy import RouterBusy
from openwrtgui.context import AppContext, build_context
from openwrtgui.lte.recover import LteRecoverBusy
from openwrtgui.lte.service import LteBusy
from openwrtgui.lte.state import NO_LTE
from openwrtgui.paths import DataDir
from openwrtgui.store import keys as keys_module
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.fake import ReplayTransport

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
HELD = "An LTE action is already running on AP1 · bench"


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    yield build_context(DataDir.at(tmp_path / "data"), token="t", port=1, simulator=SIM_DIR, web_dir=None)


def _ap1(ctx: AppContext) -> RouterRecord:
    rec = ctx.routers.get("ap1")
    assert rec is not None
    return rec


def _free(ctx: AppContext) -> bool:
    return (
        ctx.lte.action_busy("ap1") is None
        and not ctx.pool.write_lock("ap1").locked()
        and not ctx.lte.at_lock("ap1").locked()
    )


async def test_a_second_holder_gets_lte_busy(ctx: AppContext) -> None:
    rec = _ap1(ctx)
    async with ctx.lte.write_slot(rec):
        with pytest.raises(LteBusy, match=f"^{HELD}$"):
            async with ctx.lte.write_slot(rec):
                pytest.fail("a second holder got the slot")
    async with ctx.lte.write_slot(rec):  # released: the next writer gets it
        pass
    assert _free(ctx)


async def test_a_held_slot_names_the_router_and_holds_its_locks(ctx: AppContext) -> None:
    rec = _ap1(ctx)
    assert _free(ctx)
    async with ctx.lte.write_slot(rec):
        assert ctx.lte.action_busy("ap1") == HELD
        assert ctx.pool.write_lock("ap1").locked() and ctx.lte.at_lock("ap1").locked()
        assert ctx.lte.action_busy("ap2") is None  # one router's slot holds no other
    assert _free(ctx)


async def test_recover_cannot_start_while_a_slot_is_held(ctx: AppContext) -> None:
    rec = _ap1(ctx)
    preview = await ctx.lte_recover.preview("ap1")
    async with ctx.lte.write_slot(rec):
        with pytest.raises(LteRecoverBusy, match=f"^{HELD}$"):
            await ctx.lte_recover.start("ap1", preview.digest)
    assert ctx.lte_recover.busy("ap1") is None


async def test_the_slot_is_refused_while_recover_runs(ctx: AppContext) -> None:
    ctx.lte.extra_busy = lambda router_id: "LTE recovery runs on AP1 · bench"
    with pytest.raises(RouterBusy, match="^LTE recovery runs on AP1 · bench$"):
        async with ctx.lte.write_slot(_ap1(ctx)):
            pytest.fail("the slot was taken while Recover runs")
    assert _free(ctx)


async def test_an_error_inside_the_slot_releases_it(ctx: AppContext) -> None:
    with pytest.raises(RuntimeError, match="^inside$"):
        async with ctx.lte.write_slot(_ap1(ctx)):
            raise RuntimeError("inside")
    assert _free(ctx)


async def test_an_at_write_is_refused_while_a_slot_is_held(ctx: AppContext) -> None:
    async with ctx.lte.write_slot(_ap1(ctx)):
        with pytest.raises(LteBusy, match=f"^{HELD}$"):
            await ctx.lte.at_command("ap1", "AT+COPS=0", confirmed=True)
    assert not any("AT+COPS=0" in e.command for e in ctx.audit.query())


async def test_the_connection_names_the_router_its_transport_and_modem(ctx: AppContext) -> None:
    rec, t, device = await ctx.lte.connection("ap1")
    assert (rec.id, device) == ("ap1", "/dev/cdc-wdm0")
    assert isinstance(t, ReplayTransport) and t is await ctx.pool.get(rec)


async def test_no_modem_is_no_connection(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_modem(router_id: str) -> str | None:
        return None

    monkeypatch.setattr(ctx.lte, "modem_device", no_modem)
    with pytest.raises(ValueError, match=f"^{re.escape(NO_LTE)}$"):
        await ctx.lte.connection("ap1")
