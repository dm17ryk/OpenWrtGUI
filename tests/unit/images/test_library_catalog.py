"""images/library.py: catalog entries from one release's profiles.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from openwrtgui.images.library import MAX_PROFILES, LibraryError, parse_profiles

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "github"
PROFILES = (FIX / "openwrt-v25.12.5-profiles.json").read_bytes()
RELEASE: dict[str, Any] = json.loads((FIX / "openwrt-v25.12.5-release.json").read_text(encoding="utf-8"))
SHA = "d340a53f2de057a8d1d703239a22e9bd24b834dcd9a0e7397bf80861ff25cc10"
IMAGE = "openwrt-ramips-mt7620-dlink_dwr-921-c3-uboot-squashfs-sysupgrade.bin"


def _profiles(**changes: Any) -> bytes:
    doc = json.loads(PROFILES)
    doc["profiles"]["dlink_dwr-921-c3-uboot"].update(changes)
    return json.dumps(doc).encode()


def test_the_bench_release_gives_one_sysupgrade_entry() -> None:
    [e] = parse_profiles(PROFILES, RELEASE)
    assert (e.board, e.boards, e.revision, e.target) == (
        "dlink,dwr-921-c3-uboot",
        ("dlink,dwr-921-c3-uboot",),
        "r35692-b8bffeefdf",
        "ramips/mt7620",
    )
    assert (e.sha256, e.size, e.image_name) == (SHA, 11272478, IMAGE)
    assert e.title == "D-Link DWR-921 C3 (U-Boot)"
    assert (e.release_tag, e.release_name, e.prerelease) == ("v25.12.5", "DWR_921-c3-uboot-qmifix3", False)
    assert e.url.endswith("/v25.12.5/" + IMAGE)
    assert e.release_url == RELEASE["html_url"]
    assert e.published_at is not None
    # the ramtest profile has only a kernel image, so it gives no entry; factory and kernel images are ignored


def test_a_profile_with_two_boards_gives_one_entry_with_both() -> None:
    [e] = parse_profiles(_profiles(supported_devices=["a,one", "a,two"]), RELEASE)
    assert e.boards == ("a,one", "a,two")
    assert e.board == "a,one"


def test_an_image_without_its_asset_is_left_out() -> None:
    release = copy.deepcopy(RELEASE)
    release["assets"] = [a for a in release["assets"] if a["name"] != IMAGE]
    assert parse_profiles(PROFILES, release) == []


def test_an_asset_digest_that_disagrees_leaves_the_entry_out() -> None:
    release = copy.deepcopy(RELEASE)
    for a in release["assets"]:
        if a["name"] == IMAGE:
            a["digest"] = "sha256:" + "00" * 32
    assert parse_profiles(PROFILES, release) == []


def test_a_title_field_is_used_when_present() -> None:
    [e] = parse_profiles(_profiles(titles=[{"title": "X Y"}]), RELEASE)
    assert e.title == "X Y"


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\xff"])
def test_bad_profiles_json_raises(raw: bytes) -> None:
    with pytest.raises(LibraryError):
        parse_profiles(raw, RELEASE)


def test_oversized_profiles_json_raises() -> None:
    with pytest.raises(LibraryError):
        parse_profiles(b" " * (MAX_PROFILES + 1), RELEASE)
