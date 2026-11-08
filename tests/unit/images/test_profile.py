"""images/profile.py: what an image holds (packages, files, programs, configs, custom packages)."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui.images.profile import ImageFile, ProfileKey, build_profile, profile_paths
from openwrtgui.images.sysupgrade import ImageError, parse_layout

ROOT = Path(__file__).resolve().parents[3]
MINI = ROOT / "tests" / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _mini_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("mini_image", ROOT / "tools" / "mini_image.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mini_image"] = module
    spec.loader.exec_module(module)
    return module


mini = _mini_module()


def test_profile_of_the_mini_image() -> None:
    data = MINI.read_bytes()
    p = build_profile(data, "mini-r35692.bin", NOW)
    assert p.key == ProfileKey(
        board="dlink,dwr-921-c3-uboot", revision="r35692-b8bffeefdf", sha256=hashlib.sha256(data).hexdigest()
    )
    assert (p.source, p.image_name, p.image_size, p.built_at) == ("image", "mini-r35692.bin", len(data), NOW)
    assert p.boards == ("dlink,dwr-921-c3-uboot",)
    assert p.release["DISTRIB_TARGET"] == "ramips/mt7620"
    assert [c.name for c in p.custom] == ["dwr921-diag", "dwr921-internet-led", "dwr921-portctl"]
    portctl = next(c for c in p.custom if c.name == "dwr921-portctl")
    assert portctl.programs[0].path == "/usr/sbin/dwr921-portctl"
    assert portctl.programs[0].usage is not None
    assert portctl.programs[0].usage.startswith("Usage: dwr921-portctl {port-status")
    led = next(c for c in p.custom if c.name == "dwr921-internet-led")
    assert led.service == "dwr921-internet-led"
    assert led.programs[0].usage is None
    assert "sch_netem.ko" in p.modules
    assert "/sbin/swconfig" in p.programs
    assert p.configs["dropbear"]["dropbear.@dropbear[0].Port"] == "22"
    assert set(p.services) == {"dropbear", "dwr921-internet-led"}
    assert p.uci_defaults == ("20_dwr921_c3_uboot_luci",)
    assert p.firmware_len == parse_layout(data, "m").firmware_len
    sh = next(f for f in p.files if f.path == "/bin/sh")
    assert sh == ImageFile(path="/bin/sh", kind="link", size=7, mode=0o777, target="busybox")
    release = next(f for f in p.files if f.path == "/etc/openwrt_release")
    assert release.sha256 is not None
    assert "/usr/sbin/dwr921-portctl" in profile_paths(p)
    assert "/usr" not in profile_paths(p)


def test_profile_round_trips_through_json() -> None:
    p = build_profile(MINI.read_bytes(), "mini-r35692.bin", NOW)
    assert type(p).model_validate_json(p.model_dump_json()) == p


def _image(entries: dict[str, bytes | object]) -> bytes:
    root = mini.build_squashfs(entries)
    return mini.build_sysupgrade(root, kernel=b"K" * 64, metadata=mini.metadata("r1-hostile"))


def test_hostile_entries_are_data() -> None:
    base = {
        "/etc/openwrt_release": b"DISTRIB_REVISION='r1-hostile'\nDISTRIB_TARGET='x/y'\n",
        "/lib/apk/db/installed": b"P:evil\nV:1\nF:usr/bin\nR:$(reboot)\n",
        "/etc/../x": b"dots",
        "/usr/bin/$(reboot)": b"#!/bin/sh\necho 'usage: $(reboot)'\n",
        "/root/a\nb": b"newline in the name",
        "/root/loop": mini.Link("loop"),
    }
    p = build_profile(_image(base), "hostile.bin", NOW)
    paths = profile_paths(p)
    assert {"/etc/../x", "/usr/bin/$(reboot)", "/root/a\nb", "/root/loop"} <= paths
    (evil,) = p.custom
    assert evil.programs[0].path == "/usr/bin/$(reboot)"
    assert evil.programs[0].usage == "usage: $(reboot)"


def test_image_without_a_release_is_refused() -> None:
    data = _image({"/lib/apk/db/installed": b"P:a\nV:1\n"})
    with pytest.raises(
        ImageError, match=r"^x\.bin has no /etc/openwrt_release; it is not an OpenWrt root file system$"
    ):
        build_profile(data, "x.bin", NOW)


def test_image_without_a_package_database_is_refused() -> None:
    data = _image({"/etc/openwrt_release": b"DISTRIB_REVISION='r1'\n"})
    with pytest.raises(ImageError, match=r"^x\.bin has no package database \(apk or opkg\)$"):
        build_profile(data, "x.bin", NOW)


def test_rom_key_folder_and_label() -> None:
    key = ProfileKey(board="dlink,dwr-921-c3-uboot", revision="r35692-b8bffeefdf", sha256="rom")
    assert (key.folder, key.label) == ("r35692-b8bffeefdf-rom", "dlink,dwr-921-c3-uboot r35692-b8bffeefdf")
    image = ProfileKey(
        board="b", revision="r1", sha256="d340a53f2de057a8d1d703239a22e9bd24b834dcd9a0e7397bf8"
    )
    assert image.folder == "r1-d340a53f2de0"


async def test_rom_profile_from_the_simulator() -> None:
    from openwrtgui.images.profile import build_rom_profile
    from openwrtgui.simulator import SimConnector

    sim = SimConnector(ROOT / "tests" / "fixtures" / "sim")
    t = await sim.connect("192.168.1.2", 22, password=None, key_paths=[Path("app_key")])
    p = await build_rom_profile(t, "dlink,dwr-921-c3-uboot", NOW)
    image = build_profile(MINI.read_bytes(), "mini-r35692.bin", NOW)
    assert p.key == ProfileKey(board="dlink,dwr-921-c3-uboot", revision="r35692-b8bffeefdf", sha256="rom")
    assert p.firmware_len is None
    assert p.custom == image.custom
    assert profile_paths(p) == profile_paths(image)
    assert p.configs == image.configs
    assert (p.services, p.uci_defaults, p.modules, p.programs) == (
        image.services,
        image.uci_defaults,
        image.modules,
        image.programs,
    )
