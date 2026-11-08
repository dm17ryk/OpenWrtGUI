"""images/sysupgrade.py: a sysupgrade image's layout (uImage header, squashfs root, fwtool metadata)."""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import pytest

from openwrtgui.images.sysupgrade import MAX_IMAGE, ImageError, open_root, parse_layout

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (FIX / "mini-r35692.bin").read_bytes()


def test_mini_layout() -> None:
    lay = parse_layout(MINI, "mini-r35692.bin")
    assert (lay.name, lay.size, lay.sha256) == (
        "mini-r35692.bin",
        len(MINI),
        hashlib.sha256(MINI).hexdigest(),
    )
    assert (lay.uimage_name, lay.kernel_size, lay.squashfs_offset) == ("DWR_921", 4096, 64 + 4096)
    assert lay.compression == "xz"
    assert lay.firmware_len == lay.squashfs_offset + lay.squashfs_size
    assert lay.metadata is not None
    assert lay.metadata.supported_devices == ("dlink,dwr-921-c3-uboot",)
    assert lay.metadata.version["revision"] == "r35692-b8bffeefdf"
    assert lay.signed is False


def test_open_root_reads_the_release() -> None:
    root = open_root(MINI, parse_layout(MINI, "m"))
    assert b"DISTRIB_REVISION='r35692-b8bffeefdf'" in root.select("/etc/openwrt_release").read_bytes()


def test_no_metadata_is_not_a_refusal() -> None:
    cut = MINI[: MINI.rindex(b"\xde\xad\xc0\xde") + 4]
    lay = parse_layout(cut, "x.bin")
    assert lay.metadata is None
    assert lay.squashfs_size > 0


def test_signature_block_is_noted() -> None:
    signature = b"untrusted comment: signed by key\n"
    block = signature + struct.pack(">4sIBxxxI", b"FWx0", 0, 0, len(signature) + 16)
    lay = parse_layout(MINI + block, "x.bin")
    assert lay.signed is True
    assert lay.metadata is not None


def test_too_large_refused() -> None:
    with pytest.raises(
        ImageError, match=r"^x\.bin is larger than 64 MB; a sysupgrade image for these routers is not$"
    ):
        parse_layout(b"\0" * (MAX_IMAGE + 1), "x.bin")


def test_no_squashfs_refused() -> None:
    with pytest.raises(ImageError, match=r"^No squashfs root file system in x\.bin$"):
        parse_layout(b"\0" * 4096, "x.bin")


def test_truncated_squashfs_refused() -> None:
    lay = parse_layout(MINI, "m")
    with pytest.raises(ImageError, match=r"^No squashfs root file system in x\.bin$"):
        parse_layout(MINI[: lay.squashfs_offset + lay.squashfs_size // 2], "x.bin")


def test_unknown_compression_refused() -> None:
    data = bytearray(MINI)
    data[64 + 4096 + 20 : 64 + 4096 + 22] = struct.pack("<H", 6)
    with pytest.raises(ImageError, match=r"^x\.bin uses zstd compression, which this app cannot read$"):
        parse_layout(bytes(data), "x.bin")


def test_squashfs_without_a_uimage_header() -> None:
    whole = parse_layout(MINI, "m")
    root = MINI[whole.squashfs_offset : whole.squashfs_offset + whole.squashfs_size]
    lay = parse_layout(root, "root.sqfs")
    assert (lay.uimage_name, lay.kernel_size, lay.squashfs_offset) == (None, None, 0)
    assert lay.firmware_len is None


@pytest.mark.skipif(
    not os.environ.get("OWG_TEST_IMAGE"), reason="set OWG_TEST_IMAGE to the bench sysupgrade.bin"
)
def test_bench_image_layout() -> None:
    lay = parse_layout(Path(os.environ["OWG_TEST_IMAGE"]).read_bytes(), "bench.bin")
    assert (lay.size, lay.squashfs_offset, lay.squashfs_size, lay.firmware_len) == (
        11272478,
        2983593,
        8271661,
        11255254,
    )
    assert lay.sha256.startswith("d340a53f2de0")
    assert lay.metadata is not None
    assert lay.metadata.version["revision"] == "r35692-b8bffeefdf"
