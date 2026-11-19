"""Offline: the key rotation window's cleanup on an authorized_keys whose first line ends in a CR, as AP2's
does (2026-11-19 window: the cleanup found no kept line, removed nothing and left the throwaway key on
AP2)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from test_ap2_key_rotation import kept_line

from openwrtgui.onboard.rotate import remove_old_key_command

SH = shutil.which("sh")


def _grep_keeps_crs() -> bool:
    """BusyBox grep on the router keeps a CR in the line; Git for Windows' grep drops it, so there the shell
    test below would not show what AP2 does."""
    if SH is None:
        return False
    done = subprocess.run([SH, "-c", "printf 'a\\r\\n' | grep -cxF a"], capture_output=True, check=False)  # noqa: S603
    return done.stdout.strip() == b"0"


FOUND = "ssh-rsa AAAAfound azuread\\user@pc\r\nssh-rsa AAAApc user@PC\n"  # AP2's first line ends in a CR
THROWAWAY = "ssh-ed25519 AAAAnew owg-rotation-test@pc"


def test_the_kept_line_keeps_the_cr_that_grep_sees() -> None:
    assert kept_line(FOUND) == "ssh-rsa AAAAfound azuread\\user@pc\r"
    assert kept_line("\n  \nssh-rsa AAAAx k\n") == "ssh-rsa AAAAx k"
    assert kept_line("") is None


@pytest.mark.skipif(
    not _grep_keeps_crs(), reason="needs a POSIX sh whose grep keeps CRs, as the router's does"
)
def test_the_cleanup_takes_the_throwaway_key_off_a_file_with_a_cr(tmp_path: Path) -> None:
    ak = tmp_path / "authorized_keys"
    ak.write_bytes(f"{FOUND}{THROWAWAY}\n".encode())
    keep = kept_line(FOUND)
    assert keep is not None and SH is not None
    cmd = remove_old_key_command(keep, THROWAWAY).replace("/etc/dropbear", tmp_path.as_posix())
    assert subprocess.run([SH, "-c", cmd], check=False).returncode == 0  # noqa: S603
    assert ak.read_bytes() == FOUND.encode()
