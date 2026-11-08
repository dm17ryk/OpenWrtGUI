"""A sysupgrade image's layout: the uImage header, the squashfs root file system and fwtool's metadata.

The bench image (v0.5 plan, "Image rules") is a 64-byte uImage header and the kernel, an xz squashfs,
padding to a 64 KiB boundary with the jffs2 end marker, then fwtool metadata blocks, each ending in a
16-byte trailer and read from the end of the file. Nothing here runs anything from the image.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
from dataclasses import dataclass

from PySquashfsImage import SquashFsImage

MAX_IMAGE = 64 * 2**20
UIMAGE_MAGIC = b"\x27\x05\x19\x56"
UIMAGE_HEADER = 64
SQUASHFS_MAGIC = b"hsqs"
SUPERBLOCK = 96
FW_MAGIC = b"FWx0"
FW_TRAILER = 16
FW_INFO_HEADER = 8  # fwimage_header: version and flags, before the JSON
FW_SIGNATURE, FW_INFO = 0, 1
COMPRESSION = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}
READABLE = frozenset({"gzip", "lzma", "xz"})


class ImageError(ValueError):
    """The file is not a sysupgrade image this app can read; the message names the file."""


@dataclass(frozen=True)
class FwMetadata:
    supported_devices: tuple[str, ...]
    version: dict[str, str]
    text: str


@dataclass(frozen=True)
class ImageLayout:
    name: str
    size: int
    sha256: str
    uimage_name: str | None
    kernel_size: int | None
    squashfs_offset: int
    squashfs_size: int
    compression: str
    metadata: FwMetadata | None
    signed: bool

    @property
    def firmware_len(self) -> int | None:
        """Where the squashfs ends, when the kernel sits right in front of it (what a flash keeps as is)."""
        if self.kernel_size is None or UIMAGE_HEADER + self.kernel_size != self.squashfs_offset:
            return None
        return self.squashfs_offset + self.squashfs_size


def _metadata(block: bytes) -> FwMetadata | None:
    try:
        text = block.decode()
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    devices = raw.get("supported_devices")
    version = raw.get("version")
    return FwMetadata(
        tuple(str(d) for d in devices) if isinstance(devices, list) else (),
        {str(k): str(v) for k, v in version.items()} if isinstance(version, dict) else {},
        text,
    )


def _trailers(data: bytes) -> tuple[FwMetadata | None, bool]:
    metadata: FwMetadata | None = None
    signed = False
    end = len(data)
    while end >= FW_TRAILER and data[end - FW_TRAILER : end - FW_TRAILER + 4] == FW_MAGIC:
        _magic, _crc, kind, size = struct.unpack(">4sIBxxxI", data[end - FW_TRAILER : end])
        if not FW_TRAILER <= size <= end:
            break
        if kind == FW_INFO:
            metadata = metadata or _metadata(data[end - size + FW_INFO_HEADER : end - FW_TRAILER])
        elif kind == FW_SIGNATURE:
            signed = True
        else:
            break
        end -= size
    return metadata, signed


def _squashfs(data: bytes, name: str) -> tuple[int, int, int]:
    at = data.find(SQUASHFS_MAGIC)
    while at != -1:
        if at + SUPERBLOCK <= len(data):
            (compression,) = struct.unpack_from("<H", data, at + 20)
            major, minor = struct.unpack_from("<HH", data, at + 28)
            (used,) = struct.unpack_from("<Q", data, at + 40)
            if (major, minor) == (4, 0) and SUPERBLOCK <= used <= len(data) - at:
                return at, used, compression
        at = data.find(SQUASHFS_MAGIC, at + 1)
    raise ImageError(f"No squashfs root file system in {name}")


def parse_layout(data: bytes, name: str) -> ImageLayout:
    if len(data) > MAX_IMAGE:
        raise ImageError(f"{name} is larger than 64 MB; a sysupgrade image for these routers is not")
    uimage_name: str | None = None
    kernel_size: int | None = None
    if data[:4] == UIMAGE_MAGIC and len(data) >= UIMAGE_HEADER:
        (kernel_size,) = struct.unpack_from(">I", data, 12)
        uimage_name = data[32:64].rstrip(b"\0").decode("ascii", "replace")
    offset, used, compression_id = _squashfs(data, name)
    compression = COMPRESSION.get(compression_id, f"unknown ({compression_id})")
    if compression not in READABLE:
        raise ImageError(f"{name} uses {compression} compression, which this app cannot read")
    metadata, signed = _trailers(data)
    return ImageLayout(
        name=name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        uimage_name=uimage_name,
        kernel_size=kernel_size,
        squashfs_offset=offset,
        squashfs_size=used,
        compression=compression,
        metadata=metadata,
        signed=signed,
    )


def open_root(data: bytes, layout: ImageLayout) -> SquashFsImage:
    start = layout.squashfs_offset
    return SquashFsImage(io.BytesIO(data[start : start + layout.squashfs_size]))
