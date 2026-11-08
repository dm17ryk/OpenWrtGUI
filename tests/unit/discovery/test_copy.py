"""discovery/copy.py: which paths a copy takes, and the exact steps that write one file."""

from __future__ import annotations

import base64
import hashlib

import pytest

from openwrtgui.discovery.copy import SavedFile, check_copy_path, read_files, write_steps
from openwrtgui.discovery.overlay import OverlayEntry


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.exit_status = 0
        self.stderr = ""

    async def read(self, n: int) -> bytes:
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    async def close(self) -> None:
        return None


class _Streams:
    """Records what would be read; every file holds b'x'."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def stream(self, command: str) -> _Reader:
        self.commands.append(command)
        return _Reader(b"x")


def _file(path: str) -> OverlayEntry:
    return OverlayEntry(path=path, kind="file", size=1, mode="-rw-r--r--")


async def test_checklist_lists_unsafe_names_without_reading_them() -> None:
    t = _Streams()
    names = ["/root/$(reboot)", "/root/x;reboot", "/root/a b", "/root/ok.txt"]
    saved = await read_files(t, [_file(n) for n in names], strict=False)  # type: ignore[arg-type]
    assert [(f.path, f.data is None, f.sha256 is None) for f in saved] == [
        ("/root/$(reboot)", True, True),
        ("/root/x;reboot", True, True),
        ("/root/a b", True, True),
        ("/root/ok.txt", False, False),
    ]
    assert t.commands == ["cat /root/ok.txt"]


async def test_copy_refuses_unsafe_names_before_reading() -> None:
    t = _Streams()
    with pytest.raises(ValueError, match=r"^/root/x;reboot has characters a copy does not take$"):
        await read_files(t, [_file("/root/x;reboot")], strict=True)  # type: ignore[arg-type]
    assert t.commands == []


async def test_checklist_keeps_no_passwords_or_host_keys() -> None:
    t = _Streams()
    names = ["/etc/shadow", "/etc/dropbear/dropbear_ed25519_host_key", "/root/ok.txt"]
    saved = await read_files(t, [_file(n) for n in names], strict=False)  # type: ignore[arg-type]
    assert [(f.path, f.data is None) for f in saved] == [
        ("/etc/shadow", True),
        ("/etc/dropbear/dropbear_ed25519_host_key", True),
        ("/root/ok.txt", False),
    ]
    assert t.commands == ["cat /root/ok.txt"]


def test_copy_refuses_unsafe_path() -> None:
    with pytest.raises(ValueError, match=r"^/root/\$\(reboot\) has characters a copy does not take$"):
        check_copy_path("/root/$(reboot)", other_router=False)
    with pytest.raises(ValueError, match=r"^/root/\.\./etc/shadow has characters a copy does not take$"):
        check_copy_path("/root/../etc/shadow", other_router=False)
    with pytest.raises(
        ValueError,
        match=r"^/etc/dropbear/authorized_keys is the router's own key or password; it is not copied$",
    ):
        check_copy_path("/etc/dropbear/authorized_keys", other_router=True)
    check_copy_path("/etc/dropbear/authorized_keys", other_router=False)  # back to the same router: allowed
    check_copy_path("/etc/config/wifi-mirror", other_router=True)


def test_write_steps() -> None:
    data = b"bench notes\n"
    f = SavedFile(
        path="/root/notes.txt",
        kind="file",
        mode="0644",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=base64.b64encode(data).decode(),
    )
    assert write_steps(f) == [
        ("mkdir -p /root && cat > /root/notes.txt", data),
        ("chmod 0644 /root/notes.txt", None),
        ("sha256sum /root/notes.txt", None),
    ]


def test_write_steps_of_a_link() -> None:
    f = SavedFile(path="/usr/bin/x", kind="link", mode="0777", size=7, sha256=None, target="busybox")
    assert write_steps(f) == [("ln -sfn busybox /usr/bin/x", None), ("readlink /usr/bin/x", None)]
