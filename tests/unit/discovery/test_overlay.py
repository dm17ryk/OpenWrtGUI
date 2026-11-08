"""discovery/overlay.py: `ls -ldn` listings; what the overlay, packages and configs changed from the image."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from openwrtgui.discovery.commands import APK_DB, OVERLAY_LS
from openwrtgui.discovery.overlay import (
    ConfigDiff,
    OptionChange,
    diff_configs,
    diff_overlay,
    diff_packages,
    mode_bits,
    parse_ls_ldn,
)
from openwrtgui.images.apkdb import parse_apk_installed
from openwrtgui.images.profile import build_profile
from openwrtgui.simulator import SimConnector

ROOT = Path(__file__).resolve().parents[3]
MINI = ROOT / "tests" / "fixtures" / "images" / "mini-r35692.bin"
PROFILE = build_profile(MINI.read_bytes(), "mini-r35692.bin", datetime(2026, 11, 8, tzinfo=UTC))


async def _ap1_run(command: str) -> str:
    sim = SimConnector(ROOT / "tests" / "fixtures" / "sim")
    t = await sim.connect("192.168.1.1", 22, password=None, key_paths=[Path("app_key")])
    return (await t.run(command)).stdout


def test_parse_ls_ldn() -> None:
    entries, unreadable = parse_ls_ldn(
        "-rw-r--r--    1 0        0               12 Nov  7 15:24 /overlay/upper/root/notes.txt\n"
        "lrwxrwxrwx    1 0        0                7 Nov  7 15:24 /overlay/upper/bin/x -> busybox\n"
        "c---------    1 0        0          0,   0 Nov  7 15:24 /overlay/upper/etc/uci-defaults/20_x\n"
        "crw-rw-rw-    1 0        0          1,   3 Jan  1  1970 /overlay/upper/dev/null\n",
        "/overlay/upper",
    )
    assert [(e.path, e.kind) for e in entries] == [
        ("/root/notes.txt", "file"),
        ("/bin/x", "link"),
        ("/etc/uci-defaults/20_x", "whiteout"),
        ("/dev/null", "other"),
    ]
    assert entries[0].size == 12
    assert entries[0].mode == "-rw-r--r--"
    assert entries[1].target == "busybox"
    assert unreadable == 0


def test_overlay_names_with_shell_characters() -> None:
    entries, unreadable = parse_ls_ldn(
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/a b\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/it's\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/$(reboot)\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/new\n"
        "line\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /elsewhere/x\n",
        "/overlay/upper",
    )
    assert [e.path for e in entries] == ["/root/a b", "/root/it's", "/root/$(reboot)", "/root/new"]
    assert unreadable == 2


def test_mode_bits() -> None:
    assert mode_bits("-rw-r--r--") == 0o644
    assert mode_bits("-rwxr-xr-x") == 0o755
    assert mode_bits("lrwxrwxrwx") == 0o777
    assert mode_bits("-rwsr-xr-t") == 0o5755
    assert mode_bits("-rwSr--r-T") == 0o5644
    assert mode_bits("c---------") == 0


async def test_diff_overlay_against_the_mini_profile() -> None:
    entries, unreadable = parse_ls_ldn(await _ap1_run(OVERLAY_LS), "/overlay/upper")
    diff = diff_overlay(entries, unreadable, PROFILE)
    assert [e.path for e in diff.added] == [
        "/etc/init.d/wifi-mirror",
        "/usr/bin/iperf3",
        "/usr/sbin/wifi-mirror",
    ]
    assert [e.path for e in diff.replaced] == ["/etc/config/dropbear", "/lib/apk/db/installed"]
    assert diff.deleted == ("/etc/uci-defaults/20_dwr921_c3_uboot_luci",)
    assert diff.unreadable == 0


def test_whiteout_of_a_path_not_in_the_image_is_left_out() -> None:
    entries, _ = parse_ls_ldn(
        "c---------    1 0        0          0,   0 Nov  7 15:24 /overlay/upper/root/gone\n", "/overlay/upper"
    )
    assert diff_overlay(entries, 1, PROFILE).deleted == ()
    assert diff_overlay(entries, 1, PROFILE).unreadable == 1


async def test_diff_packages() -> None:
    live = parse_apk_installed(await _ap1_run(APK_DB))
    diff = diff_packages(live, PROFILE)
    assert [p.name for p in diff.added] == ["iperf3"]
    assert (diff.removed, diff.changed) == ((), ())
    newer = [p if p.name != "dwr921-portctl" else p.model_copy(update={"version": "3"}) for p in live]
    newer = [p for p in newer if p.name != "dwr921-diag"]
    diff = diff_packages(newer, PROFILE)
    assert diff.changed == (("dwr921-portctl", "2", "3"),)
    assert diff.removed == ("dwr921-diag",)


def test_diff_configs_first_boot_and_changes() -> None:
    changed = dict(PROFILE.configs["dropbear"]) | {"dropbear.@dropbear[0].Port": "2222"}
    changed.pop("dropbear.@dropbear[0].RootPasswordAuth")
    changed["dropbear.@dropbear[0].Interface"] = "lan"
    live = {name: dict(options) for name, options in PROFILE.configs.items()}
    live |= {"network": {"network.lan": "interface"}, "dropbear": changed}
    drop, net = diff_configs(live, PROFILE)
    assert net == ConfigDiff(config="network", first_boot=True, changes=())
    assert drop.config == "dropbear" and not drop.first_boot
    assert drop.changes == (
        OptionChange(key="dropbear.@dropbear[0].Interface", image=None, router="lan"),
        OptionChange(key="dropbear.@dropbear[0].Port", image="22", router="2222"),
        OptionChange(key="dropbear.@dropbear[0].RootPasswordAuth", image="on", router=None),
    )


def test_config_missing_on_the_router() -> None:
    (led,) = [d for d in diff_configs({}, PROFILE) if d.config == "dwr921-internet-led"]
    assert led.changes[0].router is None
    assert not led.first_boot
