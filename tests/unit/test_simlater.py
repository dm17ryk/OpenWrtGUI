"""ap4 (v1.0a2 D7): a simulated router whose image has block-mount, iptables, a LuCI plugin and luci-app-sqm.
Not seeded unless OPENWRTGUI_SIM_SEED names it."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.simulator import SIM_SEED_ENV, SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"
CSP_ID = "c0ffee2cf63e160c091224d95d69cdff"


def _store(tmp_path: Path) -> RouterStore:
    return RouterStore(tmp_path / "routers.json")


async def _ap4(sim: SimConnector) -> Transport:
    return await sim.connect("192.168.1.6", 22, password=None, key_paths=[Path("app_key")])


def test_ap4_is_seeded_only_when_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SIM_SEED_ENV, raising=False)
    store = _store(tmp_path)
    seed_routers(SIM_DIR, store)
    assert store.get("ap4") is None and store.get("ap1") is not None
    monkeypatch.setenv(SIM_SEED_ENV, "ap4")
    seed_routers(SIM_DIR, store)
    assert store.get("ap4") is not None


async def test_ap4_answers_its_later_images_reads() -> None:
    sim = SimConnector(SIM_DIR)
    t = await _ap4(sim)
    menu_cmd = next(c for c in sim.base_commands("ap4") if c.startswith("for f in /usr/share/luci/menu.d/"))
    menu = await t.run(menu_cmd)
    assert '"admin/network/sqm"' in menu.stdout and '"admin/system/plugins"' in menu.stdout
    assert (await t.run("test -x /sbin/block")).exit_status == 0
    assert '"/dev/sda1"' in (await t.run("ubus call luci getBlockDevices")).stdout
    assert "/mnt/usb" in (await t.run("cat /proc/mounts")).stdout
    filt = await t.run("iptables --line-numbers -w -nvxL -t filter")
    assert filt.stdout.startswith("Chain INPUT (policy ACCEPT")
    assert f"{CSP_ID}.js" in (await t.run("ls -1 /www/luci-static/resources/view/plugins")).stdout
    assert f"luci_plugins.{CSP_ID}.enabled='1'" in (await t.run("uci -X show luci_plugins")).stdout
    assert "fstab." in (await t.run("uci -X show fstab")).stdout


async def test_ap4_counters_reset_and_unmount() -> None:
    sim = SimConnector(SIM_DIR)
    t = await _ap4(sim)
    assert (await t.run("iptables -Z")).ok
    listed = await t.run("iptables --line-numbers -w -nvxL -t filter")
    assert "(policy ACCEPT 0 packets, 0 bytes)" in listed.stdout
    assert (await t.run("umount '/mnt/usb'")).ok
    assert "/mnt/usb" not in (await t.run("cat /proc/mounts")).stdout


async def test_other_routers_keep_failing_block_mount() -> None:
    sim = SimConnector(SIM_DIR)
    t = await sim.connect("192.168.1.2", 22, password=None, key_paths=[Path("app_key")])
    assert (await t.run("test -x /sbin/block")).exit_status != 0
    assert (await t.run("uci -X show luci_plugins")).stdout.strip() == "luci_plugins.global=global"


async def test_ap4_lists_its_later_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from openwrtgui.context import build_context
    from openwrtgui.paths import DataDir

    monkeypatch.setenv(SIM_SEED_ENV, "ap4")
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    ctx = build_context(DataDir.at(tmp_path / "data"), token="t", port=1, simulator=SIM_DIR, web_dir=None)
    views = {v.path: v for v in await ctx.luci.pages("ap4")}
    assert views["admin/network/sqm"].available and views["admin/network/sqm"].native is None
    assert views["admin/system/mounts"].available
    assert not views["admin/status/iptables"].available  # fw4: nft present, so LuCI shows nftables's page


def test_a_record_for_ap4_can_be_added(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(
        RouterRecord(
            id="ap4",
            name="AP4 · later image",
            host="192.168.1.6",
            auth="key",
            added_at=datetime(2026, 11, 14, 9, 0),
        )
    )
    assert store.get("ap4") is not None
