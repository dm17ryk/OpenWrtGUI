"""images/library.py: the cached catalog, the image download and the import."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from openwrtgui.images.library import RELEASES_URL, ImageLibrary
from openwrtgui.images.store import ProfileStore

FIX = Path(__file__).resolve().parents[2] / "fixtures"
MINI = (FIX / "images" / "mini-r35692.bin").read_bytes()
SHA = hashlib.sha256(MINI).hexdigest()
NAME = "mini-r35692.bin"
RELEASE: dict[str, Any] = json.loads((FIX / "github" / "openwrt-v25.12.5-release.json").read_text("utf-8"))
PROFILES: dict[str, Any] = json.loads((FIX / "github" / "openwrt-v25.12.5-profiles.json").read_bytes())
PROFILES_URL = "https://dl.test/v25.12.5/profiles.json"
IMAGE_URL = "https://dl.test/v25.12.5/" + NAME
BLOB_URL = "https://objects.test/blob/" + NAME
T0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

ImageHandler = Callable[[httpx.Request], httpx.Response]


def _release(image_url: str = IMAGE_URL) -> dict[str, Any]:
    release = copy.deepcopy(RELEASE)
    release["assets"] = [
        {"name": "profiles.json", "browser_download_url": PROFILES_URL},
        {"name": NAME, "browser_download_url": image_url},
    ]
    return release


def _profiles(size: int = len(MINI)) -> bytes:
    doc = copy.deepcopy(PROFILES)
    for image in doc["profiles"]["dlink_dwr-921-c3-uboot"]["images"]:
        if image["type"] == "sysupgrade":
            image.update(name=NAME, sha256=SHA, size=size)
    return json.dumps(doc).encode()


class Github:
    """A MockTransport GitHub whose one release describes mini-r35692.bin."""

    def __init__(self, image: ImageHandler | None = None, image_url: str = IMAGE_URL, size: int = len(MINI)):
        self.calls = {"releases": 0, "image": 0}
        self.release = _release(image_url)
        self.profiles = _profiles(size)
        self.list_status = 200
        self.image = image or (lambda _: httpx.Response(200, content=MINI))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(RELEASES_URL):
            self.calls["releases"] += 1
            if self.list_status != 200:
                return httpx.Response(self.list_status)
            return httpx.Response(200, json=[self.release])
        if url == PROFILES_URL:
            return httpx.Response(200, content=self.profiles)
        self.calls["image"] += 1
        return self.image(request)

    async def _ahandle(self, request: httpx.Request) -> httpx.Response:
        # a real network suspends here; without it one read finishes before a second one starts
        await asyncio.sleep(0)
        return self._handle(request)

    def factory(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._ahandle))


class Clock:
    """The wall clock shown as "Read at", and the monotonic seconds the cache's age is measured with."""

    def __init__(self) -> None:
        self.now = T0
        self.seconds = 1000.0

    def __call__(self) -> datetime:
        return self.now

    def mono(self) -> float:
        return self.seconds

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)
        self.seconds += seconds

    def set_back(self, seconds: int) -> None:
        """The PC's clock changed (daylight saving, a manual change): the wall clock only."""
        self.now -= timedelta(seconds=seconds)


def _library(tmp_path: Path, github: Github, clock: Clock | None = None) -> tuple[ImageLibrary, ProfileStore]:
    store = ProfileStore(tmp_path)
    clock = clock or Clock()
    return ImageLibrary(store, github.factory, clock, monotonic=clock.mono), store


async def test_a_clock_set_back_does_not_keep_a_failed_read(tmp_path: Path) -> None:
    """The 0.8.2 ledger, Task 3: a negative wall-clock age counted as fresh."""
    github, clock = Github(), Clock()
    github.list_status = 502
    library, _ = _library(tmp_path, github, clock)
    assert (await library.read()).error is not None
    clock.set_back(3600)
    clock.advance(61)  # past the minute a failed read is kept, by the monotonic clock
    github.list_status = 200
    again = await library.read()
    assert (again.error, github.calls["releases"]) == (None, 2)


async def _chunks(*parts: bytes, then: Exception | None = None) -> AsyncIterator[bytes]:
    for part in parts:
        yield part
    if then is not None:
        raise then


# --- download ------------------------------------------------------------------------------------------


async def test_download_imports_and_records_the_release(tmp_path: Path) -> None:
    library, store = _library(tmp_path, Github())
    profile = await library.download(SHA)
    assert profile.key.sha256 == SHA
    assert profile.origin == RELEASE["html_url"]
    assert profile.image_name == NAME
    assert store.list() == [profile]
    assert store.image_bytes(profile.key) == MINI


async def test_a_hash_mismatch_stores_nothing(tmp_path: Path) -> None:
    github = Github(lambda _: httpx.Response(200, content=MINI[::-1]))
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == f"{NAME} does not match its release's profiles.json; nothing was imported."
    assert store.list() == []
    assert not any(tmp_path.iterdir())


async def test_a_body_larger_than_the_catalog_size_stores_nothing(tmp_path: Path) -> None:
    github = Github(lambda _: httpx.Response(200, content=MINI + b"x"))
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == f"{NAME} is larger than its release says; nothing was imported."
    assert store.list() == []


async def test_download_without_content_length_is_capped_by_the_catalog_size(tmp_path: Path) -> None:
    served: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        for _ in range(100):
            served.append(1)
            yield b"\0" * 2**20

    github = Github(lambda _: httpx.Response(200, content=body()))
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError, match="is larger than its release says; nothing was imported.$"):
        await library.download(SHA)
    assert len(served) < 100  # stopped reading once past the cap
    assert store.list() == []


async def test_a_cut_download_stores_nothing(tmp_path: Path) -> None:
    cut = httpx.ReadError("connection reset")
    github = Github(lambda _: httpx.Response(200, content=_chunks(MINI[:1000], then=cut)))
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == "The image library on GitHub could not be reached: connection reset."
    assert store.list() == []
    assert not any(tmp_path.iterdir())


async def test_a_failing_download_gives_the_http_status(tmp_path: Path) -> None:
    library, store = _library(tmp_path, Github(lambda _: httpx.Response(404)))
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == "The image library on GitHub could not be reached: HTTP 404."
    assert store.list() == []


async def test_a_malformed_asset_url_is_a_download_error(tmp_path: Path) -> None:
    library, store = _library(
        tmp_path, Github(image_url="https://dl.test:bad/x")
    )  # https: http is not offered
    with pytest.raises(ValueError, match=r"^The image library on GitHub could not be reached: .+\.$"):
        await library.download(SHA)
    assert store.list() == []


async def test_a_second_download_of_the_same_image_is_refused(tmp_path: Path) -> None:
    started, gate = asyncio.Event(), asyncio.Event()

    async def slow() -> AsyncIterator[bytes]:
        started.set()
        await gate.wait()
        yield MINI

    github = Github(lambda _: httpx.Response(200, content=slow()))
    library, store = _library(tmp_path, github)
    first = asyncio.create_task(library.download(SHA))
    await started.wait()
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == f"{NAME} is already downloading."
    gate.set()
    assert (await first).key.sha256 == SHA
    assert len(store.list()) == 1


async def test_the_busy_mark_is_cleared_after_a_failure(tmp_path: Path) -> None:
    github = Github(lambda _: httpx.Response(500))
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError, match="HTTP 500"):
        await library.download(SHA)
    github.image = lambda _: httpx.Response(200, content=MINI)
    assert (await library.download(SHA)).key.sha256 == SHA
    assert len(store.list()) == 1


async def test_an_imported_image_is_refused(tmp_path: Path) -> None:
    github = Github()
    library, store = _library(tmp_path, github)
    store.import_image(MINI, NAME, T0)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == "This image is already imported (dlink,dwr-921-c3-uboot r35692-b8bffeefdf)"
    assert github.calls["image"] == 0  # refused before downloading


async def test_an_unknown_image_raises_key_error(tmp_path: Path) -> None:
    library, _ = _library(tmp_path, Github())
    with pytest.raises(KeyError):
        await library.download("00" * 32)


def _relabelled(github: Github, *, version_code: str | None = None, board: str | None = None) -> None:
    """Make the release's profiles.json claim another revision or board than the image really is."""
    doc = json.loads(github.profiles)
    if version_code is not None:
        doc["version_code"] = version_code
    if board is not None:
        doc["profiles"]["dlink_dwr-921-c3-uboot"]["supported_devices"] = [board]
    github.profiles = json.dumps(doc).encode()


async def test_an_image_of_another_revision_than_its_release_says_is_refused(tmp_path: Path) -> None:
    github = Github()
    _relabelled(github, version_code="r99999-0123456789")
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == (
        f"{NAME} is for dlink,dwr-921-c3-uboot r35692-b8bffeefdf, "
        "not dlink,dwr-921-c3-uboot r99999-0123456789 as its release says; nothing was imported."
    )
    assert store.list() == []


async def test_an_image_of_another_board_than_its_release_says_is_refused(tmp_path: Path) -> None:
    github = Github()
    _relabelled(github, board="other,board")
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == (
        f"{NAME} is for dlink,dwr-921-c3-uboot r35692-b8bffeefdf, "
        "not other,board r35692-b8bffeefdf as its release says; nothing was imported."
    )
    assert store.list() == []


async def test_an_unreachable_catalog_with_nothing_cached_gives_the_read_error(tmp_path: Path) -> None:
    github = Github()
    github.list_status = 502
    library, store = _library(tmp_path, github)
    with pytest.raises(ValueError) as err:
        await library.download(SHA)
    assert str(err.value) == "The image library on GitHub could not be reached: HTTP 502."
    assert store.list() == []


async def test_download_follows_a_redirect(tmp_path: Path) -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        if str(request.url) == IMAGE_URL:
            return httpx.Response(302, headers={"Location": BLOB_URL})
        assert str(request.url) == BLOB_URL
        return httpx.Response(200, content=MINI)

    library, store = _library(tmp_path, Github(redirect))
    assert (await library.download(SHA)).key.sha256 == SHA
    assert len(store.list()) == 1


async def test_download_reads_the_catalog_when_none_is_cached(tmp_path: Path) -> None:
    github = Github()
    library, _ = _library(tmp_path, github)
    await library.download(SHA)
    assert github.calls["releases"] == 1


# --- read and its cache --------------------------------------------------------------------------------


async def test_a_good_read_is_cached_for_ten_minutes_and_refresh_bypasses_it(tmp_path: Path) -> None:
    github, clock = Github(), Clock()
    library, _ = _library(tmp_path, github, clock)
    first = await library.read()
    assert [e.sha256 for e in first.entries] == [SHA]
    assert (first.read_at, first.skipped, first.error) == (T0, 0, None)
    clock.advance(599)
    assert await library.read() == first
    assert github.calls["releases"] == 1
    clock.advance(2)
    await library.read()
    assert github.calls["releases"] == 2
    await library.read(force=True)
    assert github.calls["releases"] == 3


async def test_a_failed_read_is_cached_for_one_minute(tmp_path: Path) -> None:
    github, clock = Github(), Clock()
    github.list_status = 502
    library, _ = _library(tmp_path, github, clock)
    failed = await library.read()
    assert failed.entries == ()
    assert failed.error == "The image library on GitHub could not be reached: HTTP 502."
    clock.advance(59)
    assert await library.read() == failed
    assert github.calls["releases"] == 1
    clock.advance(2)
    github.list_status = 200
    again = await library.read()
    assert (again.error, [e.sha256 for e in again.entries]) == (None, [SHA])
    assert github.calls["releases"] == 2


async def test_a_failed_read_keeps_the_last_good_entries(tmp_path: Path) -> None:
    github = Github()
    library, _ = _library(tmp_path, github)
    await library.read()
    github.list_status = 500
    failed = await library.read(force=True)
    assert failed.error is not None
    assert [e.sha256 for e in failed.entries] == [SHA]


async def test_concurrent_reads_share_one_request(tmp_path: Path) -> None:
    github = Github()
    library, _ = _library(tmp_path, github)
    first, second = await asyncio.gather(library.read(), library.read())
    assert first == second
    assert github.calls["releases"] == 1
