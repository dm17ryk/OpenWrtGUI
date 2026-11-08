"""Write the two mini sysupgrade images the tests and the simulator use (tests/fixtures/images).

`build_squashfs` is a small squashfs 4.0 writer: every metadata and data block is stored uncompressed, so
PySquashfsImage reads it with the standard library only, and no mksquashfs is needed on this PC. Each image
is laid out like the bench image: uImage header, kernel, squashfs, padding to 64 KiB, the jffs2 end marker
and fwtool metadata.

Run: uv run python tools/mini_image.py
"""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "images"
REVISIONS = ("r35692-b8bffeefdf", "r35700-0c0ffee000")
BOARD = "dlink,dwr-921-c3-uboot"

BLOCK_SIZE = 131072
BLOCK_LOG = 17
META = 8192
INVALID = 0xFFFFFFFFFFFFFFFF
NO_FRAGMENT = 0xFFFFFFFF
UNCOMPRESSED_BLOCK = 1 << 24
UNCOMPRESSED_META = 0x8000
XZ = 4
# uncompressed inodes, data and fragments; no fragments; no xattrs; uncompressed ids
FLAGS = 0x0001 | 0x0002 | 0x0008 | 0x0010 | 0x0200 | 0x0800
DIR, FILE, LINK = 1, 2, 3


@dataclass(frozen=True)
class Link:
    target: str


@dataclass
class _Node:
    name: bytes
    kind: int
    mode: int
    data: bytes = b""
    target: bytes = b""
    children: dict[bytes, _Node] = field(default_factory=dict)
    number: int = 0
    pos: int = 0  # position in the uncompressed inode stream
    blocks_start: int = 0
    dir_pos: int = 0
    listing: bytes = b""


def _ref(pos: int) -> int:
    """An inode or directory reference: metadata block start (on disk) << 16 | offset in the block."""
    return ((pos // META) * (META + 2)) << 16 | (pos % META)


def _meta_blocks(stream: bytes) -> bytes:
    out = bytearray()
    for at in range(0, len(stream), META):
        chunk = stream[at : at + META]
        out += struct.pack("<H", len(chunk) | UNCOMPRESSED_META) + chunk
    return bytes(out)


def _tree(entries: Mapping[str, bytes | Link], modes: Mapping[str, int]) -> _Node:
    root = _Node(b"", DIR, 0o755)
    for path in sorted(entries):
        parts = path.strip("/").split("/")
        node = root
        for part in parts[:-1]:
            key = part.encode()
            node = node.children.setdefault(key, _Node(key, DIR, 0o755))
        name = parts[-1].encode()
        value = entries[path]
        if isinstance(value, Link):
            node.children[name] = _Node(name, LINK, 0o777, target=value.target.encode())
        else:
            node.children[name] = _Node(name, FILE, modes.get(path, 0o644), data=value)
    return root


def _post_order(node: _Node) -> list[_Node]:
    out: list[_Node] = []
    for key in sorted(node.children):
        out += _post_order(node.children[key])
    out.append(node)
    return out


def _inode_size(node: _Node) -> int:
    if node.kind == DIR:
        return 32
    if node.kind == FILE:
        return 32 + 4 * -(-len(node.data) // BLOCK_SIZE)
    return 24 + len(node.target)


def _listing(node: _Node) -> bytes:
    out = bytearray()
    group: list[_Node] = []

    def flush() -> None:
        if not group:
            return
        first = group[0]
        out.extend(struct.pack("<III", len(group) - 1, _ref(first.pos) >> 16, first.number))
        for child in group:
            out.extend(
                struct.pack(
                    "<HhHH",
                    _ref(child.pos) & 0xFFFF,
                    child.number - first.number,
                    child.kind,
                    len(child.name) - 1,
                )
            )
            out.extend(child.name)
        group.clear()

    for key in sorted(node.children):
        child = node.children[key]
        if group and (
            len(group) == 256
            or _ref(child.pos) >> 16 != _ref(group[0].pos) >> 16
            or abs(child.number - group[0].number) > 32767
        ):
            flush()
        group.append(child)
    flush()
    return bytes(out)


def build_squashfs(
    entries: Mapping[str, bytes | Link], *, modes: Mapping[str, int] | None = None, mtime: int = 0
) -> bytes:
    """A squashfs 4.0 image of `entries` (path → bytes or Link); directories are implied by the paths."""
    root = _tree(entries, modes or {})
    nodes = _post_order(root)  # children before their directory, the root last
    for number, node in enumerate(nodes, start=1):
        node.number = number

    data = bytearray()
    offset = 96
    for node in nodes:
        if node.kind == FILE:
            node.blocks_start = offset + len(data)
            data += node.data

    pos = 0
    for node in nodes:
        node.pos = pos
        pos += _inode_size(node)

    directories = bytearray()
    for node in nodes:
        if node.kind == DIR:
            node.listing = _listing(node)
            node.dir_pos = len(directories)
            directories += node.listing

    parent = {id(child): node for node in nodes for child in node.children.values()}
    inodes = bytearray()
    for node in nodes:
        inodes += struct.pack("<HHHHII", node.kind, node.mode & 0o7777, 0, 0, mtime, node.number)
        if node.kind == DIR:
            ref = _ref(node.dir_pos)
            subdirs = sum(1 for c in node.children.values() if c.kind == DIR)
            up = parent[id(node)].number if id(node) in parent else len(nodes) + 1
            inodes += struct.pack("<IIHHI", ref >> 16, 2 + subdirs, len(node.listing) + 3, ref & 0xFFFF, up)
        elif node.kind == FILE:
            inodes += struct.pack("<IIII", node.blocks_start, NO_FRAGMENT, 0, len(node.data))
            for at in range(0, len(node.data), BLOCK_SIZE):
                inodes += struct.pack("<I", len(node.data[at : at + BLOCK_SIZE]) | UNCOMPRESSED_BLOCK)
        else:
            inodes += struct.pack("<II", 1, len(node.target)) + node.target

    inode_table_start = offset + len(data)
    inode_table = _meta_blocks(bytes(inodes))
    directory_table_start = inode_table_start + len(inode_table)
    directory_table = _meta_blocks(bytes(directories))
    id_block_start = directory_table_start + len(directory_table)
    id_block = _meta_blocks(struct.pack("<I", 0))
    id_table_start = id_block_start + len(id_block)
    id_table = struct.pack("<Q", id_block_start)
    bytes_used = id_table_start + len(id_table)

    superblock = struct.pack(
        "<IIIIIHHHHHHQQQQQQQQ",
        0x73717368,
        len(nodes),
        mtime,
        BLOCK_SIZE,
        0,
        XZ,
        BLOCK_LOG,
        FLAGS,
        1,
        4,
        0,
        _ref(root.pos),
        bytes_used,
        id_table_start,
        INVALID,
        inode_table_start,
        directory_table_start,
        INVALID,
        INVALID,
    )
    image = superblock + bytes(data) + inode_table + directory_table + id_block + id_table
    return image + b"\0" * (-len(image) % 4096)


def _uimage(kernel: bytes) -> bytes:
    def header(hcrc: int) -> bytes:
        return struct.pack(
            ">IIIIIIIBBBB32s",
            0x27051956,
            hcrc,
            0,
            len(kernel),
            0x80000000,
            0x80000000,
            zlib.crc32(kernel),
            5,
            5,
            2,
            3,
            b"DWR_921",
        )

    return header(zlib.crc32(header(0)))


def fwtool_metadata(meta: dict[str, object], before: bytes = b"") -> bytes:
    """fwtool's metadata block: the JSON, then the 16-byte trailer (magic FWx0, crc32, type 1, size)."""
    text = json.dumps(meta, indent=1).encode() + b"\n"
    size = len(text) + 16
    crc = zlib.crc32(before + text)
    return text + struct.pack(">4sIBxxxI", b"FWx0", crc, 1, size)


def build_sysupgrade(root: bytes, *, kernel: bytes, metadata: dict[str, object] | None) -> bytes:
    body = _uimage(kernel) + kernel + root
    body += b"\xff" * (-len(body) % 65536) + b"\xde\xad\xc0\xde"
    return body + (fwtool_metadata(metadata, body) if metadata is not None else b"")


def metadata(revision: str) -> dict[str, object]:
    return {
        "metadata_version": "1.1",
        "compat_version": "1.0",
        "supported_devices": [BOARD],
        "version": {
            "dist": "OpenWrt",
            "version": "SNAPSHOT",
            "revision": revision,
            "target": "ramips/mt7620",
            "board": "dlink_dwr-921-c3-uboot",
        },
    }


def _script(name: str, usage: str) -> bytes:
    return f"#!/bin/sh\n\nset -eu\n\nusage() {{\n\tcat <<'EOF'\n{usage}\nEOF\n}}\n\nusage\n".encode()


def _apk(
    name: str,
    version: str,
    text: str,
    origin: str,
    files: Mapping[str, list[str]],
    *,
    license_: str = "",
    url: str = "",
) -> str:
    lines = [
        f"P:{name}",
        f"V:{version}",
        "A:mipsel_24kc",
        f"T:{text}",
        f"U:{url}",
        f"L:{license_}",
        f"o:{origin}",
    ]
    for folder, names in files.items():
        lines.append(f"F:{folder}")
        lines += [f"R:{n}" for n in names]
    return "\n".join(lines) + "\n"


def mini_root(revision: str) -> bytes:
    newer = revision != REVISIONS[0]
    portctl_usage = "Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}"
    if newer:
        portctl_usage += "\nPorts are named by their printed labels."
    packages = [
        _apk(
            "base-files",
            "1697-r35692",
            "This package contains a base filesystem and system scripts for OpenWrt.",
            "package/base-files",
            {
                "etc": ["openwrt_release"],
                "lib/upgrade/keep.d": ["base-files"],
                "etc/uci-defaults": ["20_dwr921_c3_uboot_luci"],
            },
            license_="GPL-2.0",
        ),
        _apk(
            "busybox",
            "1.37.0-r6",
            "The Swiss Army Knife of embedded Linux.",
            "package/utils/busybox",
            {"bin": ["busybox", "sh"]},
            license_="GPL-2.0",
            url="https://busybox.net/",
        ),
        _apk(
            "dropbear",
            "2026.92-r1",
            "A small SSH2 server/client designed for small memory environments.",
            "package/network/services/dropbear",
            {"etc/config": ["dropbear"], "etc/init.d": ["dropbear"]},
            license_="MIT",
        ),
        _apk(
            "kmod-sched-netem",
            "6.18.41-r1",
            "Kernel module to emulate network delay and loss.",
            "package/kernel/linux",
            {"lib/modules/6.18.41": ["sch_netem.ko"]},
            license_="GPL-2.0",
        ),
        _apk(
            "dwr921-diag",
            "2",
            "Opt-in, bounded diagnostics for the DWR-921 BM806C modem. The installed helpers "
            "send only read-only AT and QMI queries and never start a data session or change modem state.",
            "feeds/base/network/utils/dwr921-diag",
            {"usr/bin": ["dwr921-at-probe", "dwr921-qmi-readonly"]},
        ),
        _apk(
            "dwr921-internet-led",
            "4",
            "Drives the DWR-921 C3 U-Boot Internet LED when IPv4 reachability is "
            "available through LTE or wired WAN.",
            "feeds/base/network/utils/dwr921-internet-led",
            {
                "etc/config": ["dwr921-internet-led"],
                "etc/init.d": ["dwr921-internet-led"],
                "usr/sbin": ["dwr921-internet-led"],
            },
        ),
        _apk(
            "dwr921-portctl",
            "3" if newer else "2",
            "Safe label-based enable/disable/status operations for the "
            "five external PHYs exposed by the DWR-921 C3 U-Boot swconfig switch.",
            "feeds/base/network/utils/dwr921-portctl",
            {"usr/sbin": ["dwr921-portctl"]},
        ),
    ]
    release = (
        "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='SNAPSHOT'\n"
        f"DISTRIB_REVISION='{revision}'\nDISTRIB_TARGET='ramips/mt7620'\nDISTRIB_ARCH='mipsel_24kc'\n"
        f"DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT {revision}'\nDISTRIB_TAINTS='no-all busybox'\n"
    )
    elf = b"\x7fELF\0\0\0\0"
    entries: dict[str, bytes | Link] = {
        "/etc/openwrt_release": release.encode(),
        "/lib/apk/db/installed": ("\n".join(packages) + "\n").encode(),
        "/usr/sbin/dwr921-portctl": _script("dwr921-portctl", portctl_usage),
        "/usr/bin/dwr921-at-probe": _script("dwr921-at-probe", "Usage: dwr921-at-probe [tty-device ...]"),
        "/usr/bin/dwr921-qmi-readonly": _script(
            "dwr921-qmi-readonly", "Usage: dwr921-qmi-readonly [/dev/cdc-wdmN]"
        ),
        "/usr/sbin/dwr921-internet-led": b"#!/bin/sh\n\nLED_NAME=green:internet\n",
        "/etc/init.d/dwr921-internet-led": b"#!/bin/sh /etc/rc.common\n\nSTART=97\nUSE_PROCD=1\n",
        "/etc/init.d/dropbear": b"#!/bin/sh /etc/rc.common\n\nSTART=19\nUSE_PROCD=1\n",
        "/etc/config/dropbear": (
            b"\nconfig dropbear\n\toption PasswordAuth 'on'\n"
            b"\toption RootPasswordAuth 'on'\n\toption Port '22'\n"
        ),
        "/etc/config/dhcp": (
            b"\nconfig dnsmasq\n\toption domainneeded '1'\n\toption local '/lan/'\n"
            b"\tlist server '/bench/192.168.1.1'\n\tlist server '8.8.8.8'\n"
            b"\nconfig dhcp 'lan'\n\toption interface 'lan'\n\toption ignore '1'\n"
            b"\nconfig host\n\toption name 'panel'\n"
            b"\toption mac 'f4:12:fa:f3:57:68'\n\toption ip '192.168.1.30'\n"
        ),
        "/etc/config/dwr921-internet-led": (
            b"\nconfig internet_led 'main'\n\toption enabled '1'\n\toption comment 'it'\\''s the green LED'\n"
        ),
        "/etc/uci-defaults/20_dwr921_c3_uboot_luci": b"exit 0\n",
        "/lib/modules/6.18.41/sch_netem.ko": b"\0" * 64,
        "/lib/upgrade/keep.d/base-files": b"/etc/config/\n",
        "/bin/busybox": elf + b"\0" * 120,
        "/bin/sh": Link("busybox"),
        "/sbin/swconfig": elf,
        "/usr/sbin/tc": elf,
        "/usr/bin/tcpdump": elf,
    }
    executable = [p for p, v in entries.items() if isinstance(v, bytes) and v.startswith((b"#!", b"\x7fELF"))]
    return build_squashfs(entries, modes={p: 0o755 for p in executable})


def mini_image(revision: str) -> bytes:
    return build_sysupgrade(mini_root(revision), kernel=b"K" * 4096, metadata=metadata(revision))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for revision in REVISIONS:
        path = OUT / f"mini-{revision[:6]}.bin"
        path.write_bytes(mini_image(revision))
        print(f"{path.name}: {path.stat().st_size} B")


if __name__ == "__main__":
    main()
