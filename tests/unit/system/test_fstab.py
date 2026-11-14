"""Mount points with block-mount (v1.0a2 D5): fstab as LuCI's page edits it, the rules, the uci ops."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.system.fstab import (
    FstabChange,
    FstabEntry,
    FstabGlobal,
    check_entry,
    fstab_ops,
    generate_ops,
    parse_block_devices,
    parse_detect,
    parse_fstab,
    present,
)
from openwrtgui.uci import UciOp, parse_uci_show

SIM = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
LATER = json.loads((SIM / "later" / "ap4.json").read_text("utf-8"))
UCI = {
    k: v
    for k, v in parse_uci_show((SIM / "net" / "ap4.uci").read_text("utf-8")).items()
    if k.startswith("fstab.")
}
USB = "5e1f6c2a-9b0d-4c3e-8f7a-1d2c3b4a5e6f"


def test_parse_fstab_from_ap4() -> None:
    name, settings, entries = parse_fstab(UCI)
    assert name == "cfg01a7f1"
    assert settings == FstabGlobal(auto_swap=True, auto_mount=True, delay_root=5)
    assert entries == [
        FstabEntry(section="cfg02a7f1", kind="mount", enabled=True, uuid=USB, target="/mnt/usb"),
        FstabEntry(section="cfg03a7f1", kind="swap", enabled=False, device="/dev/sda2"),
    ]


def test_block_devices_and_presence() -> None:
    devices = parse_block_devices(json.dumps(LATER["block_devices"]))
    assert [(d.dev, d.type, d.mount) for d in devices] == [
        ("/dev/sda1", "ext4", "/mnt/usb"),
        ("/dev/sda2", "swap", None),
    ]
    _, _, entries = parse_fstab(UCI)
    assert present(entries[0], devices) == devices[0]  # by UUID, case-insensitive
    assert present(entries[1], devices) == devices[1]  # by device
    assert parse_block_devices("not json") == []


def test_sections_keep_label_device_and_absent_devices() -> None:
    uci = {
        "fstab.cfg0a": "mount",
        "fstab.cfg0a.label": "backup",
        "fstab.cfg0a.target": "/mnt/backup",
        "fstab.cfg0b": "swap",
        "fstab.cfg0b.device": "/dev/sdb9",
    }
    _, _, entries = parse_fstab(uci)
    assert [(e.label, e.device) for e in entries] == [("backup", None), (None, "/dev/sdb9")]
    assert all(present(e, []) is None for e in entries)  # shown "not present", still listed
    ops = fstab_ops(None, entries, FstabChange(entries=entries))
    assert not any(op.op == "delete" and op.path.count(".") == 1 for op in ops)  # no section dropped


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/usb disk"), "mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/$(x)"), "mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/"), "own file system"),
        (FstabEntry(kind="mount", uuid=USB, target="/overlay"), "own file system"),
        (FstabEntry(kind="mount", uuid=USB, target="/tmp/x"), "own file system"),
        (FstabEntry(kind="mount", uuid="x;y", target="/mnt/usb"), "UUID"),
        (FstabEntry(kind="swap", device="/etc/passwd"), "device under /dev"),
        (FstabEntry(kind="swap"), "UUID, label or device"),
        (FstabEntry(kind="mount", uuid=USB), "needs a mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/usb", options="rw;reboot"), "mount options"),
        # final review Important 3: path tricks around the refused set
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/../tmp"), "plain mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/../overlay"), "plain mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/./overlay"), "plain mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="//overlay"), "plain mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/overlay/."), "plain mount point"),
        (FstabEntry(kind="mount", uuid=USB, target="/mnt/.."), "plain mount point"),
    ],
)
def test_values_outside_the_rules_are_refused(entry: FstabEntry, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_entry(entry)


def test_a_new_mount_and_a_removed_swap() -> None:
    name, _, entries = parse_fstab(UCI)
    new = FstabEntry(kind="mount", device="/dev/sdb1", target="/mnt/data", fstype="vfat", options="rw")
    ops = fstab_ops(name, entries, FstabChange(entries=[entries[0], new]))
    added = [
        UciOp("add", "fstab.$m2", "mount"),
        UciOp("set", "fstab.$m2.enabled", "1"),
        UciOp("set", "fstab.$m2.device", "/dev/sdb1"),
        UciOp("set", "fstab.$m2.target", "/mnt/data"),
        UciOp("set", "fstab.$m2.fstype", "vfat"),
        UciOp("set", "fstab.$m2.options", "rw"),
    ]
    assert all(op in ops for op in added)  # net_plan orders the script; a new section deletes nothing
    assert not any(op.op == "delete" and op.path.startswith("fstab.$m2") for op in ops)
    assert UciOp("delete", "fstab.cfg03a7f1") in ops


EXTROOT = {
    "fstab.cfg0e": "mount",
    "fstab.cfg0e.target": "/overlay",
    "fstab.cfg0e.uuid": "0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e",
    "fstab.cfg0e.enabled": "1",
    "fstab.cfg0f": "mount",
    "fstab.cfg0f.target": "/mnt/usb",
    "fstab.cfg0f.label": "usb+1",  # outside LABEL, as a router may have it
    "fstab.cfg0f.enabled": "true",  # hand-written: read as off, must not be rewritten
    "fstab.cfg10": "mount",
    "fstab.cfg10.target": "/rom",  # a leftover of Generate: disabled
    "fstab.cfg10.device": "/dev/mtdblock5",
    "fstab.cfg10.enabled": "0",
}


def test_an_untouched_entry_neither_blocks_nor_rewrites() -> None:
    """final review Important 2: only new or changed entries are checked and written."""
    _, _, entries = parse_fstab(EXTROOT)
    extroot, usb, rom = entries
    assert fstab_ops(None, entries, FstabChange(entries=entries)) == []
    swap = FstabEntry(kind="swap", device="/dev/sda2")
    ops = fstab_ops(None, entries, FstabChange(entries=[extroot, usb, rom, swap]))
    assert {op.path.split(".")[1] for op in ops} == {"$m4"}  # the new swap only


def test_an_extroot_entry_is_neither_changed_nor_removed() -> None:
    _, _, entries = parse_fstab(EXTROOT)
    extroot, usb, rom = entries
    with pytest.raises(ValueError, match="own file system"):
        off = extroot.model_copy(update={"enabled": False})
        fstab_ops(None, entries, FstabChange(entries=[off, usb, rom]))
    with pytest.raises(ValueError, match="LuCI or the terminal"):
        fstab_ops(None, entries, FstabChange(entries=[usb, rom]))  # /overlay left out
    assert fstab_ops(None, entries, FstabChange(entries=[extroot, usb])) == [UciOp("delete", "fstab.cfg10")]


REAL_DETECT = (
    "config 'global'\n\toption\tanon_swap\t'0'\n\toption\tauto_mount\t'1'\n\toption\tdelay_root\t'5'\n\n"
    "config 'mount'\n\toption\ttarget\t'/rom'\n\toption\tdevice\t'/dev/mtdblock5'\n\toption\tenabled\t'0'\n\n"
    "config 'mount'\n\toption\ttarget\t'/overlay'\n\toption\tdevice\t'/dev/mtdblock6'"
    "\n\toption\tenabled\t'0'\n\n"
    f"config 'mount'\n\toption\ttarget\t'/mnt/usb'\n\toption\tuuid\t'{USB}'\n\toption\tenabled\t'0'\n\n"
)


def test_generate_keeps_the_disabled_entries_block_detect_prints_for_the_routers_own_file_systems() -> None:
    """final review Important 1: on a real router block detect lists /rom and /overlay too, disabled."""
    ops = generate_ops(None, [], REAL_DETECT)
    targets = [op.value for op in ops if op.path.endswith(".target")]
    assert targets == ["/rom", "/overlay", "/mnt/usb"]
    assert UciOp("set", "fstab.$m2.enabled", "0") in ops
    enabled_overlay = REAL_DETECT.replace("'/dev/mtdblock6'\n\toption\tenabled\t'0'", "'/dev/mtdblock6'")
    with pytest.raises(ValueError, match="own file system"):
        generate_ops(None, [], enabled_overlay)  # an enabled one is still refused


def test_settings_write_every_flag() -> None:
    ops = fstab_ops("cfg01a7f1", [], FstabChange(settings=FstabGlobal(auto_mount=False)))
    assert UciOp("set", "fstab.cfg01a7f1.auto_mount", "0") in ops
    assert UciOp("set", "fstab.cfg01a7f1.anon_swap", "0") in ops


def test_generate_replaces_the_sections_with_what_block_detect_prints() -> None:
    settings, entries = parse_detect(LATER["detect"])
    assert settings.delay_root == 5
    assert [(e.kind, e.enabled, e.target) for e in entries] == [
        ("mount", False, "/mnt/usb"),
        ("swap", False, None),
    ]
    name, _, current = parse_fstab(UCI)
    ops = generate_ops(name, current, LATER["detect"])
    deletes = {op.path for op in ops if op.op == "delete"}
    assert deletes == {"fstab.cfg01a7f1", "fstab.cfg02a7f1", "fstab.cfg03a7f1"}
    assert UciOp("add", "fstab.$g", "global") in ops and UciOp("add", "fstab.$m1", "mount") in ops
