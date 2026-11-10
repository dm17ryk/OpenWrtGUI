"""The v0.6c reads in the simulator (plan Task 7): Access, LEDs and mount points, and their endpoints."""

from __future__ import annotations

import httpx

from openwrtgui.context import AppContext
from openwrtgui.luci_bridge.pages import NATIVE
from openwrtgui.simaccess import OTHER_KEY
from openwrtgui.system import commands as s
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport


async def _sim(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.access is not None
    return t


async def _refuse(ctx: AppContext, *commands: str) -> None:
    access = (await _sim(ctx)).state.access  # type: ignore[union-attr]
    assert access is not None
    real = access.answer

    def refusing(command: str) -> CommandResult | None:
        if command in commands:
            return CommandResult(command, "", "Command failed: Not found\n", 4)
        return real(command)

    access.answer = refusing  # type: ignore[method-assign]


async def test_access_of_ap2(ctx: AppContext) -> None:
    a = await ctx.access.access("ap2")
    assert a.password == "set"
    assert a.policy is None  # AP2 has no rpcd.policy section
    assert [(i.section, i.port, i.enable) for i in a.ssh] == [("main", 22, True)]
    assert (a.app_instance, a.app_interface) == ("main", "lan")
    assert "lan" in a.interfaces and a.interfaces == sorted(a.interfaces)  # the SSH card's interface list
    labels = {k.comment: k.label for k in a.keys if k.type}
    assert labels["bench@lab"] == "other"
    app = [k for k in a.keys if k.label == "app"]
    assert len(app) == 1 and app[0].fingerprint == ctx.app_key.fingerprint
    assert a.http.luci_on_network is True and a.http.redirect_https is False
    assert a.https_served is False  # simulated AP2 as the real one: nothing listens on 443
    assert [(k.name, k.kind) for k in a.repo_keys] == [
        ("openwrt-snapshots.pem", "apk"),
        ("public-key.pem", "apk"),
    ]
    assert a.missing == ()


async def test_access_without_optional_parts(ctx: AppContext) -> None:
    await _refuse(ctx, s.APK_KEYS)
    a = await ctx.access.access("ap2")
    assert a.repo_keys == []
    assert a.missing == ("repository keys",)  # neither /etc/apk/keys nor /etc/opkg/keys reads


async def test_leds_of_ap2(ctx: AppContext) -> None:
    state = await ctx.access.leds("ap2")
    assert len(state.leds) == 10
    assert [(r.section, r.sysfs, r.trigger) for r in state.rows] == [("led_lan", "green:lan", "switch0")]
    assert "eth0.2" in state.devices and state.missing == ()
    # the screen shows each trigger's own options from here (one table, the one led_ops checks against)
    assert state.trigger_options["timer"] == ("delayon", "delayoff")
    assert "default-on" not in state.trigger_options  # a trigger left out takes no options
    assert state.netdev_modes[:2] == ("link", "link_10")


async def test_mounts_without_block(ctx: AppContext) -> None:
    state = await ctx.access.mounts("ap2")
    assert state.block is False
    assert {m.target for m in state.mounts} >= {"/", "/overlay"}
    assert any(u.target == "/overlay" for u in state.usage)


async def test_reads_during_a_run(ctx_guard_live: AppContext) -> None:
    a = await ctx_guard_live.access.access("ap2")
    assert a.ssh and (await ctx_guard_live.access.leds("ap2")).leds


async def test_access_endpoints(authed: httpx.AsyncClient) -> None:
    access = (await authed.get("/api/routers/ap2/system/access")).json()
    assert access["app_instance"] == "main" and access["https_served"] is False
    assert any(k["text"] == OTHER_KEY for k in access["keys"])
    assert len((await authed.get("/api/routers/ap2/system/leds")).json()["leds"]) == 10
    assert (await authed.get("/api/routers/ap2/system/mounts")).json()["block"] is False
    assert (await authed.get("/api/routers/nope/system/access")).status_code == 404


def test_luci_pages_for_access_and_leds() -> None:
    for page in (
        "admin/system/admin",
        "admin/system/admin/password",
        "admin/system/admin/pwpolicy",
        "admin/system/admin/dropbear",
        "admin/system/admin/sshkeys",
        "admin/system/admin/uhttpd",
        "admin/system/admin/repokeys",
        "admin/system/leds",
    ):
        assert NATIVE[page] == "system", page
    assert "admin/system/mounts" not in NATIVE  # LuCI's page needs block-mount: the fallback keeps it (D8)
