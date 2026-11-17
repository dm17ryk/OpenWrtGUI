"""images/library.py: catalog entries from one release's profiles.json."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from openwrtgui.images import library
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
    pages: dict[str, httpx.Response | bytes | int] | None = None,
) -> httpx.AsyncClient:
    """GitHub stand-in; anything it does not serve answers 404, as github.com does."""
    by_url: dict[str, httpx.Response | bytes | int] = {
        _profiles_url(s["release"]["tag_name"]): s["profiles"] for s in served
    }
    by_url.update(pages or {})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if str(request.url).startswith(RELEASES_URL):
            if list_handler is not None:
                return list_handler(request)
            return httpx.Response(200, json=[s["release"] for s in served])
        body = by_url.get(str(request.url), 404)
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


PAGE = "https://github.com/dm17ryk/openwrt/releases"
LIMITED = httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(EPOCH)})
FEED = f"""<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:github.com,2008:Repository/1323348770/v24.10.8</id><title>v24.10.8</title>
    <updated>2026-07-24T23:54:19Z</updated></entry>
  <entry><id>tag:github.com,2008:Repository/1323348770/v25.12.5</id><title>{RELEASE["name"]}</title>
    <updated>2026-10-15T14:50:53Z</updated></entry>
</feed>"""


def _limited_with_pages(profiles: bytes | int = PROFILES) -> dict[str, httpx.Response | bytes | int]:
    """The API is used up; the pages answer, and only v25.12.5 carries a profiles.json (as on GitHub)."""
    return {
        f"{PAGE}/latest": httpx.Response(302, headers={"Location": f"{PAGE}/tag/v25.12.5"}),
        f"{PAGE}.atom": httpx.Response(200, text=FEED),
        f"{PAGE}/download/v25.12.5/profiles.json": profiles,
    }


async def test_a_used_up_api_reads_the_catalog_from_the_release_pages() -> None:
    async with _client([], list_handler=lambda _: LIMITED, pages=_limited_with_pages()) as client:
        entries, skipped = await fetch_catalog(client)
    [api] = parse_profiles(PROFILES, RELEASE)
    [e] = entries
    assert skipped == 0
    assert (e.sha256, e.board, e.revision, e.size, e.image_name) == (
        api.sha256,
        api.board,
        api.revision,
        api.size,
        api.image_name,
    )
    assert (e.url, e.release_tag, e.release_name, e.release_url) == (
        api.url,
        api.release_tag,
        api.release_name,
        api.release_url,
    )


async def test_a_page_release_whose_profiles_json_fails_is_counted() -> None:
    pages = _limited_with_pages(profiles=500)
    async with _client([], list_handler=lambda _: LIMITED, pages=pages) as client:
        entries, skipped = await fetch_catalog(client)
    assert (entries, skipped) == ([], 1)


async def test_an_image_name_cannot_leave_its_release_folder() -> None:
    doc = json.loads(PROFILES)
    for image in doc["profiles"][SYSUPGRADE]["images"]:
        if image["type"] == "sysupgrade":
            image["name"] = "../../evil.bin"
    pages = _limited_with_pages(profiles=json.dumps(doc).encode())
    async with _client([], list_handler=lambda _: LIMITED, pages=pages) as client:
        [e], _ = await fetch_catalog(client)
    assert e.url == f"{PAGE}/download/v25.12.5/..%2F..%2Fevil.bin"


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


def test_a_profiles_json_without_a_revision_is_unreadable() -> None:
    """The 0.8.2 ledger, Task 1: entries with an empty revision were listed, then refused at the download."""
    doc = json.loads(PROFILES)
    doc["version_code"] = ""
    with pytest.raises(LibraryError, match="no revision"):
        parse_profiles(json.dumps(doc).encode(), RELEASE)


def test_an_untitled_entry_takes_its_board_as_title() -> None:
    """The 0.8.2 ledger, Task 1: an empty title gave a blank line in Settings and "Image library: , …"."""
    [e] = parse_profiles(_profiles(titles=[]), RELEASE)
    assert e.title == "dlink,dwr-921-c3-uboot"


def _asset(release: dict[str, Any], name: str) -> dict[str, Any]:
    return next(a for a in release["assets"] if a["name"] == name)


def test_an_image_link_that_is_not_https_leaves_the_entry_out() -> None:
    """The 0.8.2 ledger (final review): only https links taken from GitHub are followed."""
    release = copy.deepcopy(RELEASE)
    _asset(release, IMAGE)["browser_download_url"] = "http://dl.test/x.bin"
    assert parse_profiles(PROFILES, release) == []


def test_an_image_whose_asset_size_disagrees_is_left_out() -> None:
    """The 0.8.2 ledger, Task 1: the asset's size must be the size profiles.json gives."""
    release = copy.deepcopy(RELEASE)
    _asset(release, IMAGE)["size"] = 11272478 + 1
    assert parse_profiles(PROFILES, release) == []


async def test_a_profiles_link_that_is_not_https_is_skipped_counted_and_not_asked() -> None:
    plain = _newer()
    _asset(plain["release"], "profiles.json")["browser_download_url"] = (
        "http://dl.test/v25.12.6/profiles.json"
    )
    seen: list[httpx.Request] = []
    async with _client([_bench(), plain], seen=seen) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 1)
    assert not any(r.url.scheme == "http" for r in seen)


async def test_a_profiles_json_without_a_link_is_counted() -> None:
    """The 0.8.2 ledger, Task 2: it was skipped silently."""
    broken = _newer()
    del _asset(broken["release"], "profiles.json")["browser_download_url"]
    async with _client([_bench(), broken]) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.5"], 1)


async def test_a_releases_list_nested_too_deep_is_the_reads_error() -> None:
    """The 0.8.2 final review: a RecursionError on the releases list escaped as a 500."""
    deep = b"[" * 200000 + b"]" * 200000
    async with _client([], list_handler=lambda _: httpx.Response(200, content=deep)) as client:
        with pytest.raises(LibraryError, match="could not be reached"):
            await fetch_catalog(client)


def _three() -> list[Served]:
    return [_bench(), _newer(), _newer(tag="v25.12.7", published="2026-11-02T10:00:00Z", sha="cd" * 32)]


async def test_the_profiles_json_files_are_asked_at_once() -> None:
    """The 0.8.2 final review: one by one under the lock, up to 20 s each."""
    served = _three()
    by_url = {_profiles_url(s["release"]["tag_name"]): s["profiles"] for s in served}
    asked: set[str] = set()
    all_asked = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(RELEASES_URL):
            return httpx.Response(200, json=[s["release"] for s in served])
        asked.add(str(request.url))
        if len(asked) == len(served):
            all_asked.set()
        await asyncio.wait_for(all_asked.wait(), 2.0)  # answers only once every file was asked
        return httpx.Response(200, content=by_url[str(request.url)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entries, skipped = await fetch_catalog(client)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.7", "v25.12.6", "v25.12.5"], 0)


async def test_a_hanging_profiles_json_ends_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library, "CATALOG_DEADLINE_S", 0.2)
    served = _three()
    by_url = {_profiles_url(s["release"]["tag_name"]): s["profiles"] for s in served}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(RELEASES_URL):
            return httpx.Response(200, json=[s["release"] for s in served])
        if "v25.12.6" in str(request.url):
            await asyncio.sleep(10)  # never answers in time
        return httpx.Response(200, content=by_url[str(request.url)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entries, skipped = await asyncio.wait_for(fetch_catalog(client), 5.0)
    assert ([e.release_tag for e in entries], skipped) == (["v25.12.7", "v25.12.5"], 1)


async def test_the_request_carries_the_updater_headers() -> None:
    seen: list[httpx.Request] = []
    async with _client([_bench()], seen=seen) as client:
        await fetch_catalog(client)
    request = seen[0]
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["user-agent"] == f"OpenWrtGUI/{APP_VERSION}"
    assert request.url.params["per_page"] == "100"
