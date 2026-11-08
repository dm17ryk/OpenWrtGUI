"""AP2's recorded discovery reads (tests/fixtures/ap2/discovery.json, 2026-11-08) against the parsers and the
flash rules. With OWG_TEST_IMAGE=<the bench sysupgrade .bin> they are also compared with the bench image."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.discovery import commands as dc
from openwrtgui.discovery.firmware import image_prefix_sha256, parse_proc_mtd
from openwrtgui.discovery.overlay import diff_packages, parse_ls_ldn
from openwrtgui.flash.plan import MARGIN
from openwrtgui.images.apkdb import parse_apk_installed
from openwrtgui.images.profile import build_profile

RECORDING = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "discovery.json").read_text(encoding="utf-8")
)
BENCH_FIRMWARE_LEN = 11255254  # the bench image's uImage + kernel + squashfs, before the padding
BENCH_IMAGE_SIZE = 11272478


def _out(command: str) -> str:
    entry = RECORDING[command]
    assert entry["exit"] == 0, (command, entry.get("stderr"))
    return str(entry["stdout"])


def _image() -> bytes:
    path = os.environ.get("OWG_TEST_IMAGE")
    if not path:
        pytest.skip("set OWG_TEST_IMAGE to the bench sysupgrade image")
    return Path(path).read_bytes()


def _kb(text: str, key: str) -> int:
    return next(int(ln.split()[1]) for ln in text.splitlines() if ln.startswith(key))


def test_overlay_listing_parses() -> None:
    entries, unreadable = parse_ls_ldn(_out(dc.OVERLAY_LS), "/overlay/upper")
    kinds = {k: sum(1 for e in entries if e.kind == k) for k in {e.kind for e in entries}}
    print(f"\n{len(entries)} overlay entries: {kinds}")
    assert entries
    assert unreadable == 0
    assert all(e.path.startswith("/") and not e.path.startswith("/overlay") for e in entries)


def test_every_listed_config_was_read() -> None:
    configs = _out(dc.CONFIG_LIST).split()
    assert configs and all(dc.uci_show(c) in RECORDING for c in configs)
    assert "wireless.default_radio0.key='<hidden>'" in _out(dc.uci_show("wireless"))


def test_packages_match_the_bench_image() -> None:
    profile = build_profile(_image(), "bench.bin", datetime(2026, 11, 8))
    live = parse_apk_installed(_out(dc.APK_DB))
    diff = diff_packages(live, profile)
    print(f"\nadded: {[p.name for p in diff.added]}")
    print(f"removed: {list(diff.removed)}; changed: {list(diff.changed)}")
    assert live
    assert diff.removed == ()


def test_firmware_partition_and_hash() -> None:
    index = parse_proc_mtd(_out(dc.PROC_MTD)).get("firmware")
    assert index is not None
    hashed = dc.firmware_hash(index, BENCH_FIRMWARE_LEN)
    print(f"\n{hashed}: {RECORDING[hashed]['seconds']} s")
    words = _out(hashed).split()
    assert len(words[0]) == 64
    assert words[0] == image_prefix_sha256(_image(), BENCH_FIRMWARE_LEN)


def test_room_for_the_image_is_short_on_ap2() -> None:
    """Finding (2026-11-08 recording): /tmp has room, but AP2 reports 8148 kB MemAvailable while the
    flash rule asks for the image plus MARGIN (15104 kB), so the app refuses to flash AP2 (ledger Task 7,
    spec O17). If the rule or AP2's memory changes, this test says so."""
    meminfo = _out(dc.MEMINFO)
    mem_kb = _kb(meminfo, "MemAvailable:")
    free_kb = _kb(meminfo, "MemFree:")
    tmp_kb = int(_out(dc.DF_TMP).splitlines()[-1].split()[3])
    need_kb = (BENCH_IMAGE_SIZE + MARGIN) // 1024
    print(f"\nMemAvailable {mem_kb} kB, MemFree {free_kb} kB, /tmp free {tmp_kb} kB; needs {need_kb} kB")
    assert tmp_kb * 1024 >= BENCH_IMAGE_SIZE
    assert mem_kb * 1024 < BENCH_IMAGE_SIZE + MARGIN


def test_validate_method_exists() -> None:
    methods = _out("ubus -v list system")
    assert '"validate_firmware_image"' in methods
    assert '"sysupgrade"' in methods


def test_tools_the_firmware_check_needs() -> None:
    assert _out("command -v sha256sum dd head").startswith("/usr/bin/sha256sum")


def test_keep_list_keeps_the_configs() -> None:
    kept = _out(dc.SYSUPGRADE_LIST).split()
    assert "/etc/config/network" in kept and "/etc/config/wireless" in kept
    owg = any(p.startswith("/etc/owg/") for p in kept)
    print(f"\n{len(kept)} files kept by a flash; /etc/owg kept: {owg}")
