"""Discovery: how a simulated router differs from the mini image, its custom packages and capabilities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.discovery.overlay import ConfigDiff, OptionChange
from openwrtgui.images.profile import build_rom_profile

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


async def test_firmware_matches_on_sim_ap2(ctx: AppContext) -> None:
    import_mini(ctx)
    r = await ctx.discovery.check_firmware("ap2")
    assert (r.matches, r.detail) == (True, "The firmware matches mini-r35692.bin")
    assert r.router_sha256 == r.image_sha256


async def test_firmware_differs_on_sim_ap1(ctx: AppContext) -> None:
    import_mini(ctx)
    r = await ctx.discovery.check_firmware("ap1")
    assert r.matches is False
    assert (
        r.detail == "The firmware differs from mini-r35692.bin (flashed from another build, or changed since)"
    )


async def test_firmware_check_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    import_mini(ctx_guard_live)
    with pytest.raises(ValueError, match=r"^The firmware check reads 1 MB of flash; not while .+ runs$"):
        await ctx_guard_live.discovery.check_firmware("ap2")


async def test_rom_profile_cannot_check(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    ctx.profiles.save(await build_rom_profile(t, "dlink,dwr-921-c3-uboot", NOW))
    with pytest.raises(ValueError, match=r"^Import the image file to check the firmware$"):
        await ctx.discovery.check_firmware("ap2")


async def test_no_profile_cannot_check(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match=r"^No imported image for dlink,dwr-921-c3-uboot"):
        await ctx.discovery.check_firmware("ap2")


async def test_summary_counts_and_owners(ctx: AppContext) -> None:
    import_mini(ctx)
    s = await ctx.discovery.summary("ap1")
    state = await ctx.discovery.state("ap1")
    assert {c.config for c in state.configs if not c.first_boot} == {"dhcp", "dropbear"}
    assert (s.files_added, s.packages_added, s.configs_changed) == (3, 1, 2)
    assert s.profile == "dlink,dwr-921-c3-uboot r35692-b8bffeefdf"
    assert "BENCHSIPGUARD · dima_night" in s.owners
    assert "lab_scratch · unknown" in s.owners
    assert s.reflash_pending is False
    assert ctx.discovery.summaries["ap1"] == s


async def test_summary_without_a_profile(ctx: AppContext) -> None:
    s = await ctx.discovery.summary("ap2")
    assert (s.profile, s.files_added, s.packages_added) == (None, 0, 0)


async def test_router_item_carries_the_summary(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    await ctx.poller.poll_all()
    items = {i["record"]["id"]: i for i in (await authed.get("/api/routers")).json()}
    assert items["ap1"]["discovery"]["files_added"] == 3


async def test_firmware_endpoint(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    r = await authed.post("/api/routers/ap2/discovery/firmware")
    assert (r.status_code, r.json()["matches"]) == (200, True)
    assert (await authed.post("/api/routers/nope/discovery/firmware")).status_code == 404


async def test_discovery_endpoint(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    r = await authed.get("/api/routers/ap1/discovery")
    assert r.status_code == 200
    body = r.json()
    assert {"overlay", "packages", "configs", "custom", "programs", "capabilities"} <= set(body)
    assert (await authed.get("/api/routers/nope/discovery")).status_code == 404
