"""Discovery: how a simulated router differs from the mini image, its custom packages and capabilities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from openwrtgui.context import AppContext
from openwrtgui.discovery.overlay import ConfigDiff, OptionChange

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def import_mini(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI.read_bytes(), "mini-r35692.bin", NOW)


async def test_state_of_sim_ap1(ctx: AppContext) -> None:
    import_mini(ctx)
    s = await ctx.discovery.state("ap1")
    assert s.profile is not None
    assert (s.board, s.revision, s.profile.revision) == (
        "dlink,dwr-921-c3-uboot",
        "r35692-b8bffeefdf",
        "r35692-b8bffeefdf",
    )
    assert s.match_note is None
    assert s.has_overlay
    assert "/usr/sbin/wifi-mirror" in [e.path for e in s.overlay.added]
    assert s.overlay.deleted == ("/etc/uci-defaults/20_dwr921_c3_uboot_luci",)
    assert [p.name for p in s.packages.added] == ["iperf3"]
    assert "/etc/config/dropbear" in s.kept_on_flash
    assert "/usr/sbin/wifi-mirror" not in s.kept_on_flash
    drop = next(c for c in s.configs if c.config == "dropbear")
    assert OptionChange(key="dropbear.@dropbear[0].Port", image="22", router="2222") in drop.changes
    assert ConfigDiff(config="network", first_boot=True, changes=()) in s.configs
    portctl = next(c for c in s.custom if c.package == "dwr921-portctl")
    assert (portctl.card, portctl.source) == ("ports", "image")
    assert portctl.programs[0].usage is not None
    led = next(c for c in s.custom if c.package == "dwr921-internet-led")
    assert (led.service, led.card) == ("dwr921-internet-led", None)
    assert [p.path for p in s.programs] == ["/usr/sbin/wifi-mirror"]  # added after flashing, no package
    assert s.programs[0].usage == "Usage: wifi-mirror {start|stop|status}"
    caps = {c.name: c for c in s.capabilities}
    assert caps["Switch"].state == "in image"
    assert caps["Throughput"].state == "added after flashing"
    assert (caps["LTE"].state, caps["LTE"].reason) == ("missing", "needs uqmi")


async def test_first_boot_configs_are_not_read(ctx: AppContext) -> None:
    import_mini(ctx)
    await ctx.discovery.state("ap1")
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    calls = getattr(t, "calls", [])
    assert "uci show wireless" not in calls  # Wi-Fi keys never reach Discovery
    assert "uci show dropbear" in calls


async def test_no_profile_note(ctx: AppContext) -> None:
    s = await ctx.discovery.state("ap2")
    assert s.profile is None
    assert s.match_note == (
        "No imported image for dlink,dwr-921-c3-uboot r35692-b8bffeefdf. "
        "Import its sysupgrade image (Settings › Images), or build a profile from this router's /rom."
    )
    assert (s.custom, s.capabilities, s.configs) == ((), (), ())


async def test_discovery_endpoint(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    r = await authed.get("/api/routers/ap1/discovery")
    assert r.status_code == 200
    body = r.json()
    assert {"overlay", "packages", "configs", "custom", "programs", "capabilities"} <= set(body)
    assert (await authed.get("/api/routers/nope/discovery")).status_code == 404
