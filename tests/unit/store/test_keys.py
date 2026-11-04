from pathlib import Path

import pytest

from openwrtgui.store import keys
from openwrtgui.store.keys import load_or_create_app_key


@pytest.fixture(autouse=True)
def _no_acl_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys, "restrict_to_user", lambda path: None)


def test_created_once(tmp_path: Path) -> None:
    a = load_or_create_app_key(tmp_path, comment="openwrtgui@TEST")
    b = load_or_create_app_key(tmp_path, comment="ignored")
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint.startswith("SHA256:")
    assert a.public_line.startswith("ssh-ed25519 ")
    assert a.public_line.endswith(" openwrtgui@TEST")
    assert b.public_line == a.public_line
    assert (tmp_path / "id_ed25519.pub").read_text(encoding="utf-8").strip() == a.public_line


def test_default_comment_names_this_pc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys.socket, "gethostname", lambda: "BENCH-PC")
    assert load_or_create_app_key(tmp_path).public_line.endswith(" openwrtgui@BENCH-PC")


def test_private_key_restricted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(keys, "restrict_to_user", calls.append)
    k = load_or_create_app_key(tmp_path, comment="c")
    assert calls == [k.private_path]
    assert k.private_path == tmp_path / "id_ed25519"
