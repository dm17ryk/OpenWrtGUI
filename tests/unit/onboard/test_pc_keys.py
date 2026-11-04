from __future__ import annotations

from pathlib import Path

import asyncssh
import pytest

from openwrtgui.onboard.pc_keys import find_pc_keys, ssh_dirs


def _key(path: Path, passphrase: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = asyncssh.generate_private_key("ssh-ed25519")
    if passphrase:  # PKCS#8: encrypting the OpenSSH format needs bcrypt, which the app does not ship
        key.write_private_key(str(path), format_name="pkcs8-pem", passphrase=passphrase)
    else:
        key.write_private_key(str(path))
    key.write_public_key(f"{path}.pub")
    return path


def test_finds_the_usual_key_names_in_order(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    rsa = _key(ssh / "id_rsa")
    ed = _key(ssh / "id_ed25519")
    _key(ssh / "other_key")
    assert find_pc_keys([ssh]) == [ed, rsa]


def test_skips_a_key_with_a_passphrase(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    _key(ssh / "id_ed25519", passphrase="secret")
    rsa = _key(ssh / "id_rsa")
    assert find_pc_keys([ssh]) == [rsa]


def test_skips_a_file_that_is_not_a_key(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("not a key", encoding="utf-8")
    assert find_pc_keys([ssh]) == []


def test_same_folder_twice_lists_each_key_once(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    ed = _key(ssh / "id_ed25519")
    assert find_pc_keys([ssh, tmp_path / "x" / ".." / ".ssh"]) == [ed]


def test_missing_folders_are_fine(tmp_path: Path) -> None:
    assert find_pc_keys([tmp_path / "nope"]) == []


def test_ssh_dirs_has_home_first_then_the_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    dirs = ssh_dirs()
    assert dirs[0] == tmp_path / "home" / ".ssh"
    assert Path.home() / ".ssh" in dirs


def test_ssh_dirs_without_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME", raising=False)
    assert ssh_dirs() == [Path.home() / ".ssh"]
