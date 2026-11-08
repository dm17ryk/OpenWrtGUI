"""Run --help and promoted tool cards on simulated routers: guarded, previewed, audited."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.discovery.tools import ToolCard, ToolCommand
from openwrtgui.guard.bench_guard import GuardLocked

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
BOARD = "dlink,dwr-921-c3-uboot"
MIRROR = ToolCard(
    board=BOARD,
    path="/usr/sbin/wifi-mirror",
    name="wifi-mirror",
    commands=(
        ToolCommand(label="status", args=("status",), write=False),
        ToolCommand(label="stop", args=("stop",), write=True),
    ),
)


def import_mini(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI.read_bytes(), "mini-r35692.bin", NOW)


async def test_help_runs_audited_and_guarded(ctx: AppContext) -> None:
    import_mini(ctx)
    plan = await ctx.discovery.plan_help("ap1", "/usr/sbin/wifi-mirror")
    assert plan.lines == ("timeout 5 /usr/sbin/wifi-mirror --help 2>&1 | head -c 8192",)
    assert plan.warnings == (
        "wifi-mirror runs on AP1 · bench for at most 5 s. "
        "A program that does not know --help may do something else.",
    )
    result = await ctx.discovery.apply_help("ap1", "/usr/sbin/wifi-mirror", plan.digest)
    assert result.output.startswith("Usage: wifi-mirror {start|stop|status}")
    assert any(e.screen == "Discovery" and "--help" in e.command for e in ctx.audit.query())


async def test_help_only_for_listed_programs(ctx: AppContext) -> None:
    import_mini(ctx)
    with pytest.raises(ValueError, match=r"^/sbin/reboot is not a custom program of AP1 · bench$"):
        await ctx.discovery.plan_help("ap1", "/sbin/reboot")


async def test_help_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    import_mini(ctx_guard_live)
    plan = await ctx_guard_live.discovery.plan_help("ap1", "/usr/sbin/wifi-mirror")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.discovery.apply_help("ap1", "/usr/sbin/wifi-mirror", plan.digest)


async def test_promoted_card_shows_and_runs(ctx: AppContext) -> None:
    import_mini(ctx)
    ctx.discovery.tools.save(MIRROR)
    state = await ctx.discovery.state("ap1")
    assert state.programs[0].has_card is True
    plan = await ctx.discovery.plan_tool("ap1", MIRROR.path, "status", {})
    assert plan.lines == ("/usr/sbin/wifi-mirror status",)
    result = await ctx.discovery.apply_tool("ap1", MIRROR.path, "status", {}, plan.digest)
    assert result.exit_status is not None


async def test_card_commands_wait_during_a_run_even_when_marked_read_only(ctx_guard_live: AppContext) -> None:
    """A user's "read-only" tick is not proof: during a run only a command the app's own read-only check
    accepts may run, and a custom program never passes it."""
    import_mini(ctx_guard_live)
    ctx_guard_live.discovery.tools.save(MIRROR)
    for label in ("status", "stop"):
        plan = await ctx_guard_live.discovery.plan_tool("ap1", MIRROR.path, label, {})
        with pytest.raises(GuardLocked):
            await ctx_guard_live.discovery.apply_tool("ap1", MIRROR.path, label, {}, plan.digest)
    assert not any(e.command.startswith("/usr/sbin/wifi-mirror") for e in ctx_guard_live.audit.query())


async def test_tool_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    prefill = await authed.post(
        f"/api/tools/{BOARD}/prefill",
        json={"path": "/usr/sbin/wifi-mirror", "usage": "Usage: wifi-mirror {start|stop|status}"},
    )
    assert [c["label"] for c in prefill.json()["commands"]] == ["start", "stop", "status"]
    saved = await authed.put(f"/api/tools/{BOARD}", json=MIRROR.model_dump())
    assert saved.status_code == 200
    assert [c["path"] for c in (await authed.get(f"/api/tools/{BOARD}")).json()] == [MIRROR.path]
    bad = MIRROR.model_dump() | {"name": ""}
    assert (await authed.put(f"/api/tools/{BOARD}", json=bad)).status_code == 422
    preview = await authed.post(
        "/api/routers/ap1/discovery/help/preview", json={"path": "/usr/sbin/wifi-mirror"}
    )
    applied = await authed.post(
        "/api/routers/ap1/discovery/help/apply",
        json={"path": "/usr/sbin/wifi-mirror", "digest": preview.json()["digest"]},
    )
    assert applied.json()["output"].startswith("Usage:")
    tool = await authed.post(
        "/api/routers/ap1/discovery/tool/preview", json={"path": MIRROR.path, "label": "status", "values": {}}
    )
    assert tool.json()["lines"] == ["/usr/sbin/wifi-mirror status"]
    gone = await authed.delete(f"/api/tools/{BOARD}", params={"path": MIRROR.path})
    assert gone.status_code == 204
