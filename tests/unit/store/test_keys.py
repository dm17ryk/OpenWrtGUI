import os
from pathlib import Path

import pytest

from openwrtgui.store import keys
from openwrtgui.store.keys import NEXT_NAME, ROTATION_NAME, AppKeyRing, load_or_create_app_key


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


def test_a_stale_pub_is_rewritten_on_load(tmp_path: Path) -> None:
    k = load_or_create_app_key(tmp_path, comment="c")
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAAstale someone@else\n", encoding="utf-8")
    assert load_or_create_app_key(tmp_path).public_line == k.public_line
    assert (tmp_path / "id_ed25519.pub").read_text(encoding="utf-8").strip() == k.public_line


# ---------------------------------------------------------------- the key ring (v1.1b, D8, rulings R4 and R6)


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_fresh_ring_has_one_key(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path, comment="openwrtgui@TEST")
    assert ring.next is None
    assert ring.login_paths() == [ring.current.private_path]
    assert ring.fingerprints() == frozenset({ring.current.fingerprint})
    assert ring.moved() == frozenset()


def test_begin_makes_a_next_key_and_offers_both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ring = AppKeyRing(tmp_path, comment="openwrtgui@TEST")
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(keys, "restrict_to_user", lambda p: seen.append((p.name, Path(f"{p}.pub").exists())))
    nxt = ring.begin()
    assert ring.next == nxt and nxt.private_path == tmp_path / NEXT_NAME
    assert nxt.fingerprint != ring.current.fingerprint
    assert nxt.public_line.endswith(" openwrtgui@TEST")
    assert ring.login_paths() == [ring.current.private_path, nxt.private_path]
    assert ring.fingerprints() == frozenset({ring.current.fingerprint, nxt.fingerprint})
    assert seen == [(NEXT_NAME, False)]  # restricted before anything else exists for it
    assert (tmp_path / ROTATION_NAME).is_file()


def test_begin_twice_is_refused(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path)
    ring.begin()
    with pytest.raises(ValueError, match="A key rotation is already under way"):
        ring.begin()


def test_moved_routers_survive_a_restart(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path)
    nxt = ring.begin()
    ring.mark_moved("ap2")
    again = AppKeyRing(tmp_path)
    assert again.moved() == frozenset({"ap2"})
    assert again.next == nxt and again.current == ring.current


def test_finish_makes_the_next_key_current_and_deletes_the_old_one(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path)
    old_private = (tmp_path / "id_ed25519").read_bytes()
    nxt = ring.begin()
    ring.mark_moved("ap2")
    new = ring.finish()
    assert new.fingerprint == nxt.fingerprint and new.private_path == tmp_path / "id_ed25519"
    assert ring.current == new and ring.next is None and ring.moved() == frozenset()
    assert ring.login_paths() == [tmp_path / "id_ed25519"]
    assert (tmp_path / "id_ed25519.pub").read_text(encoding="utf-8").strip() == nxt.public_line
    assert _names(tmp_path) == ["id_ed25519", "id_ed25519.pub"]
    assert all(p.read_bytes() != old_private for p in tmp_path.iterdir())
    assert AppKeyRing(tmp_path).current.fingerprint == nxt.fingerprint


def test_finish_without_a_rotation_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No key rotation is under way"):
        AppKeyRing(tmp_path).finish()


def test_a_finish_cut_after_the_replace_is_completed_on_load(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path)
    nxt = ring.begin()
    ring.mark_moved("ap2")
    os.replace(tmp_path / NEXT_NAME, tmp_path / "id_ed25519")  # finish's step 1, then the app stopped
    again = AppKeyRing(tmp_path)
    assert again.current.fingerprint == nxt.fingerprint and again.next is None
    assert _names(tmp_path) == ["id_ed25519", "id_ed25519.pub"]
    assert (tmp_path / "id_ed25519.pub").read_text(encoding="utf-8").strip() == nxt.public_line


def test_unmark_moved_forgets_a_router(tmp_path: Path) -> None:
    """Final review F1: a router given the old key again (re-added, removed) must move again."""
    ring = AppKeyRing(tmp_path)
    ring.begin()
    ring.mark_moved("ap2")
    ring.unmark_moved("ap2")
    ring.unmark_moved("never-moved")  # nothing to forget: no error
    assert ring.moved() == frozenset() and AppKeyRing(tmp_path).moved() == frozenset()


def test_a_finish_whose_pub_write_fails_still_leaves_one_usable_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review F4: after the replace, the ring holds the new key even if the .pub cannot be written; a
    later load completes the rest."""
    ring = AppKeyRing(tmp_path)
    nxt = ring.begin()

    def full_disk(path: Path, text: str) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(keys, "write_atomic", full_disk)
    new = ring.finish()
    assert new.fingerprint == nxt.fingerprint and ring.next is None
    assert ring.login_paths() == [tmp_path / "id_ed25519"] and (tmp_path / "id_ed25519").exists()
    monkeypatch.undo()
    monkeypatch.setattr(keys, "restrict_to_user", lambda path: None)
    again = AppKeyRing(tmp_path)
    assert again.current.fingerprint == nxt.fingerprint and again.next is None
    assert _names(tmp_path) == ["id_ed25519", "id_ed25519.pub"]


def test_a_next_key_left_without_its_rotation_is_dropped(tmp_path: Path) -> None:
    ring = AppKeyRing(tmp_path)
    ring.begin()
    (tmp_path / ROTATION_NAME).unlink()  # begin stopped before it wrote the rotation: no router has the key
    again = AppKeyRing(tmp_path)
    assert again.next is None and _names(tmp_path) == ["id_ed25519", "id_ed25519.pub"]
