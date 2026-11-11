"""A backup archive checked on the PC before a restore (plan D11): what it holds, and why it is refused."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import struct
import tarfile

import asyncssh
import pytest

from openwrtgui.system.archive import (
    MAX_ARCHIVE,
    ArchiveRefused,
    dropbear_key_fingerprint,
    read_archive,
    restore_refusals,
)

SYSTEM = "config system\n\toption hostname 'OpenWrt'\n\toption zonename 'UTC'\n"
NETWORK = (
    "config interface 'loopback'\n\toption device 'lo'\n\toption ipaddr '127.0.0.1'\n"
    "config interface 'lan'\n\toption device 'br-lan'\n\toption proto 'static'\n"
    "\toption ipaddr '192.168.1.2'\n\toption netmask '255.255.255.0'\n"
)


def _ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _ed25519_dropbear(key: asyncssh.SSHKey) -> bytes:
    """dropbear's ed25519 key file: the type, then 64 bytes (32 private, 32 public)."""
    blob = key.public_data
    (n,) = struct.unpack(">I", blob[:4])
    rest = blob[4 + n :]
    (m,) = struct.unpack(">I", rest[:4])
    public = rest[4 : 4 + m]
    return _ssh_string(b"ssh-ed25519") + _ssh_string(os.urandom(32) + public)


def _archive(files: dict[str, bytes], *, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    return buf.getvalue()


def test_archive_lists_files_and_hashes() -> None:
    host = asyncssh.generate_private_key("ssh-ed25519")
    app = asyncssh.generate_private_key("ssh-ed25519", comment="user@pc")
    keys = app.export_public_key("openssh")
    data = _archive(
        {
            "etc/config/system": SYSTEM.encode(),
            "etc/config/network": NETWORK.encode(),
            "etc/dropbear/dropbear_ed25519_host_key": _ed25519_dropbear(host),
            "etc/dropbear/authorized_keys": keys,
        }
    )
    info = read_archive(data)
    assert [f.path for f in info.files] == [
        "/etc/config/system",
        "/etc/config/network",
        "/etc/dropbear/dropbear_ed25519_host_key",
        "/etc/dropbear/authorized_keys",
    ]
    assert info.files[0].sha256 == hashlib.sha256(SYSTEM.encode()).hexdigest()
    assert info.files[0].size == len(SYSTEM.encode())
    assert info.hostname == "OpenWrt"
    assert info.addresses == ("127.0.0.1", "192.168.1.2")
    assert info.host_keys == (host.get_fingerprint("sha256"),)
    assert info.authorized_keys == keys.decode()


def _link(name: str, target: str, kind: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"x" * (MAX_ARCHIVE + 1), "larger than 4 MiB"),
        (b"PK\x03\x04 not a gzip", "not a gzip archive"),
        (gzip.compress(b"not a tar"), "not a tar archive"),
        (_archive({"../etc/passwd": b"x"}), "outside /etc"),
        (_archive({"/etc/shadow": b"x"}), "absolute path"),
        (_archive({"etc/../../root/x": b"x"}), "outside /etc"),
        (_archive({"usr/bin/x": b"x"}), "outside /etc"),
        (_archive({}, extra=[_link("etc/config/x", "/etc/shadow", tarfile.SYMTYPE)]), "a link or a device"),
        (_archive({}, extra=[_link("etc/x", "etc/config/system", tarfile.LNKTYPE)]), "a link or a device"),
    ],
)
def test_archive_refusals(data: bytes, reason: str) -> None:
    with pytest.raises(ArchiveRefused, match=reason):
        read_archive(data)


def test_dropbear_key_fingerprint() -> None:
    ed = asyncssh.generate_private_key("ssh-ed25519")
    assert dropbear_key_fingerprint(_ed25519_dropbear(ed)) == ed.get_fingerprint("sha256")

    rsa = asyncssh.generate_private_key("ssh-rsa", key_size=2048)
    blob = rsa.public_data  # string "ssh-rsa", mpint e, mpint n: dropbear's file starts the same way
    fake_private = _ssh_string(b"\x01") * 3  # d, p, q: not part of the fingerprint
    assert dropbear_key_fingerprint(blob + fake_private) == rsa.get_fingerprint("sha256")

    with pytest.raises(ValueError):
        dropbear_key_fingerprint(b"\x00\x00")


def _info(**files: bytes) -> object:
    return read_archive(_archive({name.replace("__", "/"): data for name, data in files.items()}))


def test_restore_refusals() -> None:
    host = asyncssh.generate_private_key("ssh-ed25519")
    app = asyncssh.generate_private_key("ssh-ed25519", comment="user@pc")
    other = asyncssh.generate_private_key("ssh-ed25519")
    pinned = host.get_fingerprint("sha256")
    app_fp = {app.get_fingerprint("sha256")}

    def refusals(info: object) -> list[str]:
        return restore_refusals(
            info, router_name="AP2", address="192.168.1.2", port=22, pinned=pinned, app=app_fp
        )  # type: ignore[arg-type]

    good = _info(
        etc__config__network=NETWORK.encode(),
        etc__dropbear__dropbear_ed25519_host_key=_ed25519_dropbear(host),
        etc__dropbear__authorized_keys=app.export_public_key("openssh"),
    )
    assert refusals(good) == []

    assert refusals(_info(etc__dropbear__dropbear_ed25519_host_key=_ed25519_dropbear(other))) == [
        "this backup is from another router: its SSH host key is not AP2's"
    ]
    moved = NETWORK.replace("192.168.1.2", "192.168.1.1")
    assert refusals(_info(etc__config__network=moved.encode())) == [
        "this backup puts AP2 at 127.0.0.1, 192.168.1.1; the app reaches it at 192.168.1.2"
    ]
    assert refusals(_info(etc__dropbear__authorized_keys=other.export_public_key("openssh"))) == [
        "after the restore the app could not log in to AP2"
    ]
    assert refusals(_info(etc__config__system=SYSTEM.encode())) == []  # no keys, no network: nothing to lose


DROPBEAR = "config dropbear 'main'\n\toption enable '1'\n\toption Port '22'\n"


def test_restore_refuses_ssh_the_app_could_not_reach() -> None:
    """A backup whose dropbear config leaves nothing on the app's port, on every interface or the one with
    the router's address, would end "not back": it is refused before anything is sent (review, D11)."""

    def refusals(dropbear: str | None) -> list[str]:
        files = {"etc__config__network": NETWORK.encode()}
        if dropbear is not None:
            files["etc__config__dropbear"] = dropbear.encode()
        info = _info(**files)
        return restore_refusals(
            info, router_name="AP2", address="192.168.1.2", port=22, pinned=None, app=set()
        )  # type: ignore[arg-type]

    unreachable = ["after the restore nothing on AP2 listens for SSH on port 22, where the app connects"]
    assert refusals(DROPBEAR) == []
    assert refusals(None) == []  # no dropbear config in the backup: the router keeps its own
    assert refusals(DROPBEAR + "\toption Interface 'lan'\n") == []  # lan holds 192.168.1.2
    assert refusals("config dropbear\n") == []  # dropbear's defaults: on, port 22, every interface
    assert refusals(DROPBEAR.replace("'22'", "'2222'")) == unreachable
    assert refusals(DROPBEAR.replace("enable '1'", "enable '0'")) == unreachable
    assert refusals(DROPBEAR + "\toption Interface 'wan'\n") == unreachable
