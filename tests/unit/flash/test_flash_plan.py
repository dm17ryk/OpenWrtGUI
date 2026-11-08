"""flash/plan.py: the flash preview: board, hash, RAM and isolation checks, then the exact steps."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui.flash.plan import KEEP_LINE, FlashFacts, FlashRequest, flash_plan, fw_path
from openwrtgui.images.profile import ProfileKey, build_profile
from openwrtgui.timer import arm_command

MINI_BYTES = (Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin").read_bytes()
SHA = hashlib.sha256(MINI_BYTES).hexdigest()
PROFILE = build_profile(MINI_BYTES, "mini-r35692.bin", datetime(2026, 11, 8, tzinfo=UTC))
REQ = FlashRequest(board="dlink,dwr-921-c3-uboot", revision="r35692-b8bffeefdf", sha256=SHA)
FACTS = FlashFacts(
    board_name="dlink,dwr-921-c3-uboot",
    revision="r35692-b8bffeefdf",
    mem_available_kb=20480,
    tmp_free_kb=24000,
    owg_dir=True,
    dhcp_on_own=None,
)
PATH = f"/tmp/owg/fw-{SHA[:12]}.bin"


def test_fw_path() -> None:
    assert fw_path(SHA) == PATH


def test_plan_keep_settings() -> None:
    p = flash_plan("AP2 · dev", PROFILE, MINI_BYTES, REQ, FACTS)
    assert p.lines == (
        "mkdir -p /tmp/owg",
        f"cat > {PATH}  # stdin: mini-r35692.bin ({len(MINI_BYTES)} B, sha256 {SHA[:12]})",
        f"sha256sum {PATH}",
        f'ubus call system validate_firmware_image \'{{"path":"{PATH}"}}\'',
        f"sysupgrade -T {PATH}",
        KEEP_LINE,
        arm_command("flash", 2, [f"sysupgrade {PATH}"]),
    )
    assert p.upload_command == f"cat > {PATH}"
    assert len(p.digest) == 16
    assert p.warnings == (
        "AP2 · dev reboots and is off the network for about 3 minutes. "
        "Once sysupgrade starts it cannot be stopped.",
    )


def test_keep_line_only_when_the_app_saved_files() -> None:
    p = flash_plan("AP2 · dev", PROFILE, MINI_BYTES, REQ, FlashFacts(**{**FACTS.__dict__, "owg_dir": False}))
    assert KEEP_LINE not in p.lines


def test_plan_without_settings_needs_isolation() -> None:
    req = REQ.model_copy(update={"keep_settings": False})
    with pytest.raises(ValueError, match=r"^Confirm that AP2 · dev is isolated from the bench LAN first$"):
        flash_plan("AP2 · dev", PROFILE, MINI_BYTES, req, FACTS)
    p = flash_plan("AP2 · dev", PROFILE, MINI_BYTES, req.model_copy(update={"isolated": True}), FACTS)
    assert p.lines[-1] == arm_command("flash", 2, [f"sysupgrade -n {PATH}"])
    assert KEEP_LINE not in p.lines


def test_image_for_another_board_refused() -> None:
    other = FlashFacts(**{**FACTS.__dict__, "board_name": "other,board"})
    with pytest.raises(
        ValueError, match=r"^This image is for dlink,dwr-921-c3-uboot; AP2 · dev is other,board$"
    ):
        flash_plan("AP2 · dev", PROFILE, MINI_BYTES, REQ, other)


def test_image_changed_on_disk_refused() -> None:
    with pytest.raises(
        ValueError, match=r"^mini-r35692\.bin changed on disk since it was imported; import it again$"
    ):
        flash_plan("AP2 · dev", PROFILE, MINI_BYTES + b"x", REQ, FACTS)


def test_rom_profile_refused() -> None:
    rom = PROFILE.model_copy(
        update={"source": "rom", "key": ProfileKey(board=REQ.board, revision=REQ.revision, sha256="rom")}
    )
    with pytest.raises(ValueError, match=r"^Flash needs the image file: import it in Settings › Images$"):
        flash_plan("AP2 · dev", rom, MINI_BYTES, REQ, FACTS)


def test_image_without_boards_refused() -> None:
    bare = PROFILE.model_copy(update={"boards": ()})
    with pytest.raises(
        ValueError, match=r"^The image does not say which boards it is for; flash it with LuCI"
    ):
        flash_plan("AP2 · dev", bare, MINI_BYTES, REQ, FACTS)


def test_not_enough_ram_refused() -> None:
    low = FlashFacts(**{**FACTS.__dict__, "mem_available_kb": 2048})
    with pytest.raises(ValueError, match=r"^AP2 · dev has 2 MB of RAM free; the image needs 5 MB in /tmp$"):
        flash_plan("AP2 · dev", PROFILE, MINI_BYTES, REQ, low)


async def test_read_facts_from_the_simulator() -> None:
    from types import SimpleNamespace

    from openwrtgui.flash.plan import read_facts
    from openwrtgui.simulator import SimConnector

    sim = SimConnector(Path(__file__).resolve().parents[2] / "fixtures" / "sim")
    t = await sim.connect("192.168.1.2", 22, password=None, key_paths=[Path("app_key")])
    net = SimpleNamespace(own_interface="lan", dhcp=())  # only these two NetworkState fields are read
    facts = await read_facts(t, "dlink,dwr-921-c3-uboot", "r35692-b8bffeefdf", net)  # type: ignore[arg-type]
    assert (facts.mem_available_kb, facts.tmp_free_kb, facts.owg_dir, facts.dhcp_on_own) == (
        20480,
        24000,
        True,
        None,
    )


def test_dhcp_warning() -> None:
    p = flash_plan(
        "AP1 · bench", PROFILE, MINI_BYTES, REQ, FlashFacts(**{**FACTS.__dict__, "dhcp_on_own": "lan"})
    )
    assert (
        "AP1 · bench hands out addresses on lan. "
        "Devices there get no new address while it flashes (about 3 minutes)." in p.warnings
    )
