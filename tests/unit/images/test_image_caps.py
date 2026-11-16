"""An imported image's root file system has entry and size caps (v1.0b1 D6)."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pytest

from openwrtgui.images.profile import MAX_ENTRIES, MAX_UNPACKED, _entries
from openwrtgui.images.sysupgrade import ImageError


def _root(entries: Iterable[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(root=SimpleNamespace(riter=lambda: iter(entries)))


def _file(path: str, size: int = 0) -> SimpleNamespace:
    return SimpleNamespace(path=path, is_dir=False, is_file=True, size=size)


def test_an_image_within_the_caps_is_read() -> None:
    assert set(_entries(_root([_file("/etc/openwrt_release", 10)]), "ok.bin")) == {"/etc/openwrt_release"}


def test_an_image_of_more_entries_is_refused() -> None:
    with pytest.raises(ImageError, match=f"big.bin holds more than {MAX_ENTRIES} entries"):
        _entries(_root(_file(f"/f{i}") for i in range(MAX_ENTRIES + 1)), "big.bin")


def test_an_image_that_unpacks_too_large_is_refused() -> None:
    with pytest.raises(ImageError, match="bomb.bin unpacks to more than 512 MiB"):
        _entries(_root([_file("/a", MAX_UNPACKED), _file("/b", 1)]), "bomb.bin")
