"""images/store.py: imported images and their profiles under <data>/profiles."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui.images.profile import ProfileKey
from openwrtgui.images.store import ProfileStore

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (FIX / "mini-r35692.bin").read_bytes()
NEWER = (FIX / "mini-r35700.bin").read_bytes()
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def test_import_dedupe_delete(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    p = store.import_image(MINI, "mini-r35692.bin", NOW)
    folder = tmp_path / "dlink,dwr-921-c3-uboot" / p.key.folder
    assert (folder / "image.bin").read_bytes() == MINI
    assert (folder / "profile.json").is_file()
    assert store.list() == [p]
    assert store.get(p.key) == p
    with pytest.raises(
        ValueError, match=r"^This image is already imported \(dlink,dwr-921-c3-uboot r35692-b8bffeefdf\)$"
    ):
        store.import_image(MINI, "again.bin", NOW)
    store.delete(p.key)
    assert store.list() == []
    assert not folder.exists()


def test_image_bytes_checks_the_hash(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    p = store.import_image(MINI, "mini-r35692.bin", NOW)
    assert store.image_bytes(p.key) == MINI
    (tmp_path / "dlink,dwr-921-c3-uboot" / p.key.folder / "image.bin").write_bytes(MINI + b"x")
    with pytest.raises(
        ValueError, match=r"^mini-r35692\.bin changed on disk since it was imported; import it again$"
    ):
        store.image_bytes(p.key)


def test_rom_profile_has_no_image(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    p = store.import_image(MINI, "mini-r35692.bin", NOW)
    rom = p.model_copy(
        update={
            "key": ProfileKey(board=p.key.board, revision=p.key.revision, sha256="rom"),
            "source": "rom",
            "image_name": None,
            "image_size": None,
            "firmware_len": None,
        }
    )
    store.save(rom)
    with pytest.raises(ValueError, match=r"^Flash needs the image file: import it in Settings › Images$"):
        store.image_bytes(rom.key)


def test_match_prefers_the_image(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    p = store.import_image(MINI, "mini-r35692.bin", NOW)
    rom = p.model_copy(
        update={"key": ProfileKey(board=p.key.board, revision=p.key.revision, sha256="rom"), "source": "rom"}
    )
    store.save(rom)
    store.import_image(NEWER, "mini-r35700.bin", NOW)
    assert store.match("dlink,dwr-921-c3-uboot", "r35692-b8bffeefdf") == p
    assert store.match("dlink,dwr-921-c3-uboot", "r35700-0c0ffee000") is not None
    assert store.match("other,board", "r35692-b8bffeefdf") is None
    store.delete(p.key)
    assert store.match("dlink,dwr-921-c3-uboot", "r35692-b8bffeefdf") == rom


def test_unreadable_profile_is_left_out(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    p = store.import_image(MINI, "mini-r35692.bin", NOW)
    broken = tmp_path / "dlink,dwr-921-c3-uboot" / "r1-rom"
    broken.mkdir()
    (broken / "profile.json").write_text("{not json", encoding="utf-8")
    assert store.list() == [p]
    assert hashlib.sha256(store.image_bytes(p.key)).hexdigest() == p.key.sha256
