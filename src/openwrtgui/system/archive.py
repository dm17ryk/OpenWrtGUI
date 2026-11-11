"""A backup archive checked on the PC before a restore (v0.6c plan D11). The archive holds secrets (the
password hash, the SSH host keys, the Wi-Fi keys): it is read in memory only, nothing of it is logged, and
only the public part of a host key is ever derived from it."""

from __future__ import annotations

import base64
import hashlib
import io
import struct
import tarfile
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict

from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.system.access import dropbear_instances
from openwrtgui.system.sshkeys import parse_authorized_keys

MAX_ARCHIVE = 4 * 1024 * 1024  # AP2's own backup is 7 KB; /tmp holds the upload (about 8 MB of RAM free)
MAX_UNPACKED = 16 * 1024 * 1024
GZIP = b"\x1f\x8b"
_HOST_KEY_DIR = "/etc/dropbear/"


class ArchiveRefused(ValueError):
    """The archive is not one this app restores; the message says why."""


class ArchiveFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str  # absolute, as on the router
    size: int
    sha256: str


class ArchiveInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: tuple[ArchiveFile, ...]
    hostname: str | None
    addresses: tuple[str, ...]  # every interface's fixed IPv4 address in etc/config/network
    interfaces: tuple[tuple[str, str], ...] = ()  # (interface, fixed IPv4 address) in etc/config/network
    ssh: tuple[tuple[int, str], ...] | None = (
        None  # enabled dropbear instances (port, interface); None: no config
    )
    host_keys: tuple[str, ...]  # fingerprints of the archive's SSH host keys
    authorized_keys: str | None  # the file's text (public keys), None when the archive has none
    has_network: bool


def _path(name: str) -> str:
    if name.startswith("/"):
        raise ArchiveRefused(f"The backup holds an absolute path: {name}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if ".." in parts or not parts or parts[0] != "etc":
        raise ArchiveRefused(f"The backup holds a path outside /etc: {name}")
    return "/" + "/".join(parts)


def _members(data: bytes) -> list[tuple[str, bytes]]:
    if len(data) > MAX_ARCHIVE:
        raise ArchiveRefused("The backup is larger than 4 MiB")
    if not data.startswith(GZIP):
        raise ArchiveRefused("This is not a gzip archive")
    out: list[tuple[str, bytes]] = []
    unpacked = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                path = _path(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ArchiveRefused(f"The backup holds a link or a device: {member.name}")
                unpacked += member.size
                if unpacked > MAX_UNPACKED:
                    raise ArchiveRefused("The backup unpacks to more than 16 MiB")
                handle = tar.extractfile(member)
                out.append((path, handle.read() if handle else b""))
    except (tarfile.TarError, EOFError, OSError) as e:
        raise ArchiveRefused("This is not a tar archive") from e
    return out


def _interfaces(network: str) -> tuple[tuple[str, str], ...]:
    shown = parse_uci_file("network", network)
    out: list[tuple[str, str]] = []
    for path, value in shown.items():
        section, _, option = path.rpartition(".")
        if option != "ipaddr" or shown.get(section) != "interface":
            continue
        out.extend((section.split(".", 1)[1], v.split("/", 1)[0]) for v in value.split())
    return tuple(out)


def _ssh(dropbear: str) -> tuple[tuple[int, str], ...]:
    """Where dropbear listens after a restore: each enabled instance's port and interface ("" is all)."""
    return tuple(
        (i.port, i.interface) for i in dropbear_instances(parse_uci_file("dropbear", dropbear)) if i.enable
    )


def read_archive(data: bytes) -> ArchiveInfo:
    texts: dict[str, bytes] = {}
    for path, raw in _members(data):  # tar keeps the last copy of a path: so does the proof
        texts.pop(path, None)
        texts[path] = raw
    members = list(texts.items())
    host_keys: list[str] = []
    for path, raw in members:
        name = path.removeprefix(_HOST_KEY_DIR)
        if path.startswith(_HOST_KEY_DIR) and name.startswith("dropbear_") and name.endswith("_host_key"):
            try:
                host_keys.append(dropbear_key_fingerprint(raw))
            except ValueError:
                continue  # a key this app cannot read is not compared
    system = texts.get("/etc/config/system")
    network = texts.get("/etc/config/network")
    keys = texts.get("/etc/dropbear/authorized_keys")
    dropbear = texts.get("/etc/config/dropbear")
    interfaces = _interfaces(network.decode(errors="replace")) if network is not None else ()
    hostname = None
    if system is not None:
        hostname = parse_uci_file("system", system.decode(errors="replace")).get("system.@system[0].hostname")
    return ArchiveInfo(
        files=tuple(
            ArchiveFile(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            for path, raw in members
        ),
        hostname=hostname,
        addresses=tuple(a for _, a in interfaces),
        interfaces=interfaces,
        ssh=_ssh(dropbear.decode(errors="replace")) if dropbear is not None else None,
        host_keys=tuple(host_keys),
        authorized_keys=keys.decode(errors="replace") if keys is not None else None,
        has_network=network is not None,
    )


def _ssh_string(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(data):
        raise ValueError("not a dropbear key")
    (n,) = struct.unpack(">I", data[offset : offset + 4])
    end = offset + 4 + n
    if end > len(data):
        raise ValueError("not a dropbear key")
    return data[offset + 4 : end], end


def _pack(*parts: bytes) -> bytes:
    return b"".join(struct.pack(">I", len(p)) + p for p in parts)


def dropbear_key_fingerprint(blob: bytes) -> str:
    """The SHA256 fingerprint of a dropbear host key file's public part (the private part is not kept)."""
    key_type, offset = _ssh_string(blob, 0)
    if key_type == b"ssh-ed25519":
        pair, _ = _ssh_string(blob, offset)
        if len(pair) != 64:
            raise ValueError("not a dropbear ed25519 key")
        public = _pack(key_type, pair[32:])
    elif key_type == b"ssh-rsa":
        e, offset = _ssh_string(blob, offset)
        n, _ = _ssh_string(blob, offset)
        public = _pack(key_type, e, n)
    elif key_type.startswith(b"ecdsa-sha2-"):
        curve, offset = _ssh_string(blob, offset)
        point, _ = _ssh_string(blob, offset)
        public = _pack(key_type, curve, point)
    else:
        raise ValueError("not a dropbear key")
    return "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode().rstrip("=")


def restore_refusals(
    info: ArchiveInfo,
    *,
    router_name: str,
    address: str,
    port: int,
    pinned: str | None,
    app: Collection[str],
) -> list[str]:
    """Why this archive would leave the router unreachable for the app, or is another router's (D11)."""
    out: list[str] = []
    if pinned is not None and info.host_keys and pinned not in info.host_keys:
        out.append(f"this backup is from another router: its SSH host key is not {router_name}'s")
    if info.has_network and address not in info.addresses:
        where = ", ".join(info.addresses) or "no fixed address"
        out.append(f"this backup puts {router_name} at {where}; the app reaches it at {address}")
    if info.authorized_keys is not None:
        present = {k.fingerprint for k in parse_authorized_keys(info.authorized_keys) if k.fingerprint}
        if not present & set(app):
            out.append(f"after the restore the app could not log in to {router_name}")
    if info.ssh is not None:
        # the interface holding the app's address; without a network config the router keeps its own
        mine = {name for name, a in info.interfaces if a == address}
        if not any(
            p == port and (where == "" or not info.has_network or where in mine) for p, where in info.ssh
        ):
            out.append(
                f"after the restore nothing on {router_name} listens for SSH on port {port}, "
                "where the app connects"
            )
    return out
