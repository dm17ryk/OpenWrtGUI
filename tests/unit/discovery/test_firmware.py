"""discovery/firmware.py: the firmware partition from /proc/mtd, and the image's prefix hash."""

from __future__ import annotations

import hashlib

from openwrtgui.discovery.firmware import image_prefix_sha256, parse_proc_mtd

PROC_MTD = (
    "dev:    size   erasesize  name\n"
    'mtd0: 00030000 00010000 "u-boot"\n'
    'mtd3: 00fb0000 00010000 "firmware"\n'
    'mtd6: 00670000 00010000 "rootfs_data"\n'
)


def test_parse_proc_mtd() -> None:
    assert parse_proc_mtd(PROC_MTD) == {"u-boot": 0, "firmware": 3, "rootfs_data": 6}
    assert parse_proc_mtd("") == {}


def test_image_prefix_sha256() -> None:
    assert image_prefix_sha256(b"abcdef", 3) == hashlib.sha256(b"abc").hexdigest()
