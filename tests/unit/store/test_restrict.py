"""User-only access for the app's secrets (the SSH key, the backup folder and its archives)."""

import stat
import sys
from pathlib import Path

import pytest

from openwrtgui.store.keys import restrict_to_user, user_only_mode


def test_a_folder_keeps_its_search_bit(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    assert user_only_mode(folder) == 0o700  # without x, nothing can be created inside


def test_a_file_is_read_write_only(tmp_path: Path) -> None:
    file = tmp_path / "id_ed25519"
    file.write_bytes(b"k")
    assert user_only_mode(file) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes; Windows uses icacls")
def test_a_restricted_folder_still_takes_a_file(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    restrict_to_user(folder)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    archive = folder / "ap2-20261110-090000.tar.gz.part"
    with archive.open("xb") as sink:
        sink.write(b"\x1f\x8b")
    restrict_to_user(archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
