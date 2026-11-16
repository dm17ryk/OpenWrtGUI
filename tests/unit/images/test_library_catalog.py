"""images/library.py: catalog entries from one release's profiles.json."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from openwrtgui.images.library import MAX_PROFILES, RELEASES_URL, LibraryError, fetch_catalog, parse_profiles
from openwrtgui.version import APP_VERSION

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


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\xff", b"[" * 200000])
def test_bad_profiles_json_raises(raw: bytes) -> None:
    with pytest.raises(LibraryError):
        parse_profiles(raw, RELEASE)


def test_oversized_profiles_json_raises() -> None:
    with pytest.raises(LibraryError):
        parse_profiles(b" " * (MAX_PROFILES + 1), RELEASE)


def test_a_release_with_null_assets_gives_no_entries() -> None:
    assert parse_profiles(PROFILES, {**RELEASE, "assets": None}) == []


# --- fetch_catalog -------------------------------------------------------------------------------------

NEW_SHA = "ab" * 32
EPOCH = 1_800_000_000
Served = dict[str, Any]  # {"release": GitHub release item, "profiles": bytes or an int HTTP status}
SYSUPGRADE = "dlink_dwr-921-c3-uboot"


def _profiles_url(tag: str) -> str:
    return f"https://dl.test/{tag}/profiles.json"


def _bench() -> Served:
    release = copy.deepcopy(RELEASE)
    for a in release["assets"]:
        if a["name"] == "profiles.json":
            a["browser_download_url"] = _profiles_url(release["tag_name"])
    return {"release": release, "profiles": PROFILES}


def _newer(tag: str = "v25.12.6", published: str = "2026-11-01T10:00:00Z", sha: str = NEW_SHA) -> Served:
    served = _bench()
    release = served["release"]
    release.update(tag_name=tag, name=tag, published_at=published)
    for a in release["assets"]:
        if a["name"] == IMAGE:
            a["digest"] = f"sha256:{sha}"
        if a["name"] == "profiles.json":
            a["browser_download_url"] = _profiles_url(tag)
    doc = json.loads(PROFILES)
    for image in doc["profiles"][SYSUPGRADE]["images"]:
        if image["type"] == "sysupgrade":
            image["sha256"] = sha
    served["profiles"] = json.dumps(doc).encode()
    return served


def _client(
    served: list[Served],
    *,
    list_handler: Callable[[httpx.Request], httpx.Response] | None = None,
    seen: list[httpx.Request] | None = None,
) -> httpx.AsyncClient:
    by_url = {_profiles_url(s["release"]["tag_name"]): s["profiles"] for s in served}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if str(request.url).startswith(RELEASES_URL):
            if list_handler is not None:
                return list_handler(request)
            return httpx.Response(200, json=[s["release"] for s in served])
        body = by_url[str(request.url)]
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_catalog_is_read_from_every_release() -> None:
    async with _client([_bench(), _newer()]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], [e.sha256 for e in entries], skipped) == (
        ["v25.12.6", "v25.12.5"],
        [NEW_SHA, SHA],
        0,
    )


async def test_the_same_image_in_two_releases_is_listed_once_under_the_newest() -> None:
    async with _client([_bench(), _newer(sha=SHA)]) as client:
        entries, _ = await fetch_catalog(client)
    assert [(e.sha256, e.release_tag) for e in entries] == [(SHA, "v25.12.6")]


async def test_a_release_without_profiles_json_is_left_out_quietly() -> None:
    bare = {"release": {**RELEASE, "tag_name": "v25.12.9", "assets": None}, "profiles": b""}
    async with _client([bare, _bench()]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 0)


@pytest.mark.parametrize("bad", [500, b"{", b"[" * 200000, b" " * (MAX_PROFILES + 1)])
async def test_an_unreadable_profiles_json_is_skipped_and_counted(bad: bytes | int) -> None:
    broken = _newer()
    broken["profiles"] = bad
    async with _client([_bench(), broken]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 1)


async def test_a_malformed_profiles_url_is_skipped_and_counted() -> None:
    broken = _newer()
    for a in broken["release"]["assets"]:
        if a["name"] == "profiles.json":
            a["browser_download_url"] = "http://dl.test:bad/x"
    async with _client([_bench(), broken]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 1)


async def test_drafts_are_ignored() -> None:
    draft = _newer()
    draft["release"]["draft"] = True
    async with _client([_bench(), draft]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 0)


async def test_the_rate_limit_names_the_reset_time() -> None:
    def limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(EPOCH)})

    expected = datetime.fromtimestamp(EPOCH).strftime("%H:%M")
    async with _client([], list_handler=limited) as client:
        with pytest.raises(LibraryError) as err:
            await fetch_catalog(client)
    assert str(err.value) == f"GitHub's limit for anonymous reads is reached; try again after {expected}."


async def test_an_unreachable_github_is_one_clear_error() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with _client([], list_handler=boom) as client:
        with pytest.raises(LibraryError) as err:
            await fetch_catalog(client)
    assert str(err.value) == "The image library on GitHub could not be reached: boom."


async def test_a_failing_list_gives_the_http_status() -> None:
    async with _client([], list_handler=lambda _: httpx.Response(502)) as client:
        with pytest.raises(LibraryError) as err:
            await fetch_catalog(client)
    assert str(err.value) == "The image library on GitHub could not be reached: HTTP 502."


async def test_the_request_carries_the_updater_headers() -> None:
    seen: list[httpx.Request] = []
    async with _client([_bench()], seen=seen) as client:
        await fetch_catalog(client)
    request = seen[0]
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["user-agent"] == f"OpenWrtGUI/{APP_VERSION}"
    assert request.url.params["per_page"] == "100"
