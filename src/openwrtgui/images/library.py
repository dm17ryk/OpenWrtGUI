"""The image library: firmware builds listed in the profiles.json of dm17ryk/openwrt releases.

When the API's hourly budget for this network is used up, the release pages are read instead (github_pages).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict

from openwrtgui.github_pages import PageRelease, releases_from_pages, reset_time, used_up
from openwrtgui.images.profile import Profile
from openwrtgui.images.store import ProfileStore
from openwrtgui.images.sysupgrade import MAX_IMAGE
from openwrtgui.version import APP_VERSION

RELEASES_URL = "https://api.github.com/repos/dm17ryk/openwrt/releases"
RELEASES_PAGE = "https://github.com/dm17ryk/openwrt/releases"
MAX_PROFILES = 2**20
PROFILES_NAME = "profiles.json"
CACHE_SECONDS = 600
ERROR_CACHE_SECONDS = 60
CATALOG_DEADLINE_S = 60.0  # every release's profiles.json together; one not read by then is skipped
FETCH_AT_ONCE = 4  # profiles.json files asked at the same time
_PAGE_HEADERS = {"User-Agent": f"OpenWrtGUI/{APP_VERSION}"}
_HEADERS = {"Accept": "application/vnd.github+json", **_PAGE_HEADERS}


class LibraryError(ValueError):
    """A profiles.json that cannot be read as a catalog."""


class LibraryEntry(BaseModel):
    """One sysupgrade image offered by one release."""

    model_config = ConfigDict(frozen=True)

    sha256: str
    boards: tuple[str, ...]
    revision: str
    target: str
    title: str
    image_name: str
    size: int
    url: str
    release_tag: str
    release_name: str
    release_url: str
    published_at: datetime | None
    prerelease: bool

    @property
    def board(self) -> str:
        return self.boards[0]


def _title(profile: dict[str, Any]) -> str:
    titles = profile.get("titles")
    if isinstance(titles, list) and titles and isinstance(titles[0], dict):
        first = titles[0]
        if first.get("title"):
            return str(first["title"])
        parts = [str(first[k]) for k in ("vendor", "model", "variant") if first.get(k)]
        if parts:
            return " ".join(parts)
    return ""


def _https(url: object) -> bool:
    """Only https links taken from GitHub's answers are followed (the 0.8.2 final review)."""
    return isinstance(url, str) and url.startswith("https://")


def _published(release: dict[str, Any]) -> datetime | None:
    raw = release.get("published_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry(
    profile: Any,
    *,
    revision: str,
    target: str,
    release: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    download_base: str | None,
) -> LibraryEntry | None:
    if not isinstance(profile, dict):
        return None
    devices = profile.get("supported_devices")
    if not isinstance(devices, list) or not devices or not all(isinstance(d, str) and d for d in devices):
        return None
    images = profile.get("images")
    if not isinstance(images, list):
        return None
    image = next((i for i in images if isinstance(i, dict) and i.get("type") == "sysupgrade"), None)
    if image is None:
        return None
    name, sha256, size = image.get("name"), image.get("sha256"), image.get("size")
    if not isinstance(name, str) or not isinstance(sha256, str) or not sha256:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return None
    if download_base is not None:  # read from the pages: no asset list; the download is checked by its sha256
        url = f"{download_base}/{quote(name, safe='')}"
    else:
        asset = assets.get(name)
        if asset is None or not _https(asset.get("browser_download_url")):
            return None
        digest = asset.get("digest")
        if digest and digest != f"sha256:{sha256}":
            return None
        listed = asset.get("size")
        if isinstance(listed, int) and not isinstance(listed, bool) and listed != size:
            return None  # the asset is not the file profiles.json describes (the 0.8.2 ledger, Task 1)
        url = str(asset["browser_download_url"])
    tag = str(release.get("tag_name", ""))
    return LibraryEntry(
        sha256=sha256,
        boards=tuple(devices),
        revision=revision,
        target=target,
        title=_title(profile),
        image_name=name,
        size=size,
        url=url,
        release_tag=tag,
        release_name=str(release.get("name") or tag),
        release_url=str(release.get("html_url", "")),
        published_at=_published(release),
        prerelease=bool(release.get("prerelease")),
    )


def parse_profiles(
    raw: bytes, release: dict[str, Any], download_base: str | None = None
) -> list[LibraryEntry]:
    """Entries for the sysupgrade images of one release; `release` is a GitHub releases API item.

    `download_base` is the release's download folder when the release was read from the pages, which list no
    assets: each image's URL is then that folder plus the image's name.
    """
    if len(raw) > MAX_PROFILES:
        raise LibraryError(f"{PROFILES_NAME} is larger than {MAX_PROFILES} bytes")
    try:
        doc = json.loads(raw)
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError
        raise LibraryError(f"{PROFILES_NAME} is not valid JSON: {exc}") from exc
    except RecursionError as exc:  # deeply nested input well under MAX_PROFILES
        raise LibraryError(f"{PROFILES_NAME} is nested too deeply") from exc
    if not isinstance(doc, dict):
        raise LibraryError(f"{PROFILES_NAME} is not a JSON object")
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        return []
    revision, target = str(doc.get("version_code", "")), str(doc.get("target", ""))
    assets = _assets(release)
    entries = (
        _entry(
            p, revision=revision, target=target, release=release, assets=assets, download_base=download_base
        )
        for p in profiles.values()
    )
    return [e for e in entries if e is not None]


def _assets(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = release.get("assets")
    if not isinstance(raw, list):
        return {}
    return {str(a["name"]): a for a in raw if isinstance(a, dict) and a.get("name")}


async def _profiles_bytes(client: httpx.AsyncClient, url: str) -> tuple[int, bytes | None]:
    """The HTTP status and the body of profiles.json; the body is None when it cannot be downloaded or is over
    MAX_PROFILES, and the status is 0 when no answer came."""
    try:
        async with client.stream(
            "GET", url, headers=_HEADERS, timeout=20.0, follow_redirects=True
        ) as response:
            if response.status_code // 100 != 2:
                return response.status_code, None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_PROFILES:
                    return response.status_code, None
            return response.status_code, bytes(body)
    except (httpx.HTTPError, httpx.InvalidURL):
        return 0, None


def _unreachable(reason: str) -> LibraryError:
    return LibraryError(f"The image library on GitHub could not be reached: {reason}.")


def _reason(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def _list_error(response: httpx.Response) -> LibraryError:
    if used_up(response):
        reset = reset_time(response)
        if reset is not None:
            return LibraryError(
                f"GitHub's limit for anonymous reads is reached; try again after {reset.strftime('%H:%M')}."
            )
        return LibraryError("GitHub's limit for anonymous reads is reached; try again later.")
    return _unreachable(f"HTTP {response.status_code}")


def _newest_first(release: dict[str, Any]) -> tuple[bool, float]:
    published = _published(release)
    return (published is None, -published.timestamp() if published else 0.0)


# One release to read: the release (an API item, or one made from the pages), where its profiles.json is,
# and the download folder when the pages had no asset list (a 404 then means it has no profiles.json).
_Source = tuple[dict[str, Any], str, str | None]


def _from_page(page: PageRelease) -> _Source:
    folder = f"{RELEASES_PAGE}/download/{page.tag}"
    release = {
        "tag_name": page.tag,
        "name": page.title,
        "html_url": f"{RELEASES_PAGE}/tag/{page.tag}",
        "published_at": page.updated.isoformat() if page.updated else None,
    }
    return release, f"{folder}/{PROFILES_NAME}", folder


async def _source_entries(client: httpx.AsyncClient, source: _Source) -> list[LibraryEntry] | None:
    """One release's entries: [] when the pages say it has no profiles.json (404), None when that file cannot
    be read or its link is not https (the 0.8.2 final review)."""
    release, profiles_url, download_base = source
    if not _https(profiles_url):
        return None
    status, raw = await _profiles_bytes(client, profiles_url)
    if download_base is not None and status == 404:
        return []
    if raw is None:
        return None
    try:
        return parse_profiles(raw, release, download_base)
    except LibraryError:
        return None


async def _every_source(client: httpx.AsyncClient, sources: list[_Source]) -> list[list[LibraryEntry] | None]:
    """Each release's entries, in order, asked FETCH_AT_ONCE at a time within CATALOG_DEADLINE_S; a release
    not read by then, or whose read failed, is None (the 0.8.2 final review: one by one, 20 s each)."""
    gate = asyncio.Semaphore(FETCH_AT_ONCE)

    async def one(source: _Source) -> list[LibraryEntry] | None:
        async with gate:
            return await _source_entries(client, source)

    tasks = [asyncio.ensure_future(one(s)) for s in sources]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=CATALOG_DEADLINE_S)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return [t.result() if t in done and t.exception() is None else None for t in tasks]


async def _collect(
    client: httpx.AsyncClient, sources: list[_Source], skipped: int = 0
) -> tuple[list[LibraryEntry], int]:
    """Every release's entries, newest first, each image once (under the newest release that lists it), and
    the releases that could not be read added to `skipped`."""
    entries: list[LibraryEntry] = []
    seen: set[str] = set()
    for found in await _every_source(client, sorted(sources, key=lambda s: _newest_first(s[0]))):
        if found is None:
            skipped += 1
            continue
        for entry in found:
            if entry.sha256 not in seen:
                seen.add(entry.sha256)
                entries.append(entry)
    return entries, skipped


async def fetch_catalog(client: httpx.AsyncClient) -> tuple[list[LibraryEntry], int]:
    """Entries of every published release, newest first, and the number of unreadable profiles.json files."""
    try:
        response = await client.get(RELEASES_URL, params={"per_page": 100}, headers=_HEADERS, timeout=20.0)
    except httpx.HTTPError as exc:
        raise _unreachable(_reason(exc)) from exc
    if used_up(response):
        try:
            pages = await releases_from_pages(client, RELEASES_PAGE, _PAGE_HEADERS)
        except (httpx.HTTPError, ValueError) as exc:
            raise _list_error(response) from exc
        return await _collect(client, [_from_page(p) for p in pages])
    if response.status_code // 100 != 2:
        raise _list_error(response)
    try:
        releases = response.json()
    except (ValueError, RecursionError) as exc:  # RecursionError: nested too deeply (the 0.8.2 final review)
        raise _unreachable("the answer is not JSON") from exc
    if not isinstance(releases, list):
        raise _unreachable("the answer is not a list of releases")

    sources: list[_Source] = []
    no_link = 0  # a profiles.json asset without a link: counted (the 0.8.2 ledger, Task 2)
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        asset = _assets(release).get(PROFILES_NAME)
        if asset is None:
            continue
        if asset.get("browser_download_url"):
            sources.append((release, str(asset["browser_download_url"]), None))
        else:
            no_link += 1
    return await _collect(client, sources, skipped=no_link)


class LibraryRead(BaseModel):
    """What the last look at GitHub found; `entries` survive a later failed read."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[LibraryEntry, ...] = ()
    read_at: datetime | None = None
    skipped: int = 0
    error: str | None = None


class ImageLibrary:
    """The catalog (cached) and the download of one of its images into the profile store."""

    def __init__(
        self,
        profiles: ProfileStore,
        client_factory: Callable[[], httpx.AsyncClient],
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._profiles = profiles
        self._client_factory = client_factory
        self._clock = clock
        self._cached: LibraryRead | None = None
        self._lock = asyncio.Lock()
        self._busy: set[str] = set()

    def _fresh(self, cached: LibraryRead, now: datetime) -> bool:
        if cached.read_at is None:
            return False
        limit = ERROR_CACHE_SECONDS if cached.error else CACHE_SECONDS
        return (now - cached.read_at).total_seconds() < limit

    async def read(self, force: bool = False) -> LibraryRead:
        async with self._lock:
            now = self._clock()
            previous = self._cached
            if not force and previous is not None and self._fresh(previous, now):
                return previous
            try:
                async with self._client_factory() as client:
                    entries, skipped = await fetch_catalog(client)
            except LibraryError as exc:
                result = LibraryRead(
                    entries=previous.entries if previous else (),
                    read_at=now,
                    skipped=previous.skipped if previous else 0,
                    error=str(exc),
                )
            else:
                result = LibraryRead(entries=tuple(entries), read_at=now, skipped=skipped)
            self._cached = result
            return result

    async def download(self, sha256: str) -> Profile:
        """Fetch one catalog image and import it. KeyError: not in the catalog; ValueError: anything else."""
        read = await self.read()
        entry = next((e for e in read.entries if e.sha256 == sha256), None)
        if entry is None:
            if read.error:
                raise ValueError(read.error)
            raise KeyError(sha256)
        if sha256 in self._busy:
            raise ValueError(f"{entry.image_name} is already downloading.")
        self._busy.add(sha256)
        try:
            imported = await asyncio.to_thread(self._profiles.list)  # reads the data folder (0.8.2 ledger)
            known = next((p for p in imported if p.key.sha256 == sha256), None)
            if known is not None:
                raise ValueError(f"This image is already imported ({known.key.label})")
            data = await self._fetch(entry)
            return await asyncio.to_thread(
                self._profiles.import_image,
                data,
                entry.image_name,
                self._clock(),
                origin=entry.release_url,
                expect=(entry.board, entry.revision),
            )
        finally:
            self._busy.discard(sha256)

    async def _fetch(self, entry: LibraryEntry) -> bytes:
        limit = min(entry.size, MAX_IMAGE)
        too_large = ValueError(f"{entry.image_name} is larger than its release says; nothing was imported.")
        body = bytearray()
        digest = hashlib.sha256()  # hashed as it arrives, not 64 MB at once on the event loop (0.8.2 ledger)
        try:
            async with (
                self._client_factory() as client,
                client.stream(
                    "GET", entry.url, headers=_HEADERS, timeout=60.0, follow_redirects=True
                ) as response,
            ):
                if response.status_code // 100 != 2:
                    raise _unreachable(f"HTTP {response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    raise too_large
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > limit:
                        raise too_large
                    digest.update(chunk)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise _unreachable(_reason(exc)) from exc
        if digest.hexdigest() != entry.sha256:
            raise ValueError(
                f"{entry.image_name} does not match its release's profiles.json; nothing was imported."
            )
        return await asyncio.to_thread(bytes, body)  # the 64 MB copy off the event loop too
