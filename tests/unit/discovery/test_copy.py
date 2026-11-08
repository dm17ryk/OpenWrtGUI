"""discovery/copy.py: which paths a copy takes, and the exact steps that write one file."""

from __future__ import annotations

import base64
import hashlib

import pytest

from openwrtgui.discovery.copy import SavedFile, check_copy_path, write_steps


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
