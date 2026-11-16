"""The image library: firmware builds listed in the profiles.json of dm17ryk/openwrt releases."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from openwrtgui.version import APP_VERSION

RELEASES_URL = "https://api.github.com/repos/dm17ryk/openwrt/releases"
MAX_PROFILES = 2**20
PROFILES_NAME = "profiles.json"
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": f"OpenWrtGUI/{APP_VERSION}"}


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
    asset = assets.get(name)
    if asset is None or not asset.get("browser_download_url"):
        return None
    digest = asset.get("digest")
    if digest and digest != f"sha256:{sha256}":
        return None
    tag = str(release.get("tag_name", ""))
    return LibraryEntry(
        sha256=sha256,
        boards=tuple(devices),
        revision=revision,
        target=target,
        title=_title(profile),
        image_name=name,
        size=size,
        url=str(asset["browser_download_url"]),
        release_tag=tag,
        release_name=str(release.get("name") or tag),
        release_url=str(release.get("html_url", "")),
        published_at=_published(release),
        prerelease=bool(release.get("prerelease")),
    )


def parse_profiles(raw: bytes, release: dict[str, Any]) -> list[LibraryEntry]:
    """Entries for the sysupgrade images of one release; `release` is a GitHub releases API item."""
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
        _entry(p, revision=revision, target=target, release=release, assets=assets) for p in profiles.values()
    )
    return [e for e in entries if e is not None]


def _assets(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = release.get("assets")
    if not isinstance(raw, list):
        return {}
    return {str(a["name"]): a for a in raw if isinstance(a, dict) and a.get("name")}


async def _profiles_bytes(client: httpx.AsyncClient, url: str) -> bytes | None:
    """The body of profiles.json, or None when it cannot be downloaded or is over MAX_PROFILES."""
    try:
        async with client.stream(
            "GET", url, headers=_HEADERS, timeout=20.0, follow_redirects=True
        ) as response:
            if response.status_code // 100 != 2:
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_PROFILES:
                    return None
            return bytes(body)
    except httpx.HTTPError:
        return None


def _unreachable(reason: str) -> LibraryError:
    return LibraryError(f"The image library on GitHub could not be reached: {reason}.")


def _list_error(response: httpx.Response) -> LibraryError:
    if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
        try:
            reset = datetime.fromtimestamp(int(response.headers["X-RateLimit-Reset"]))
        except (KeyError, ValueError, OverflowError, OSError):
            pass
        else:
            return LibraryError(
                f"GitHub's limit for anonymous reads is reached; try again after {reset.strftime('%H:%M')}."
            )
    return _unreachable(f"HTTP {response.status_code}")


def _newest_first(release: dict[str, Any]) -> tuple[bool, float]:
    published = _published(release)
    return (published is None, -published.timestamp() if published else 0.0)


async def fetch_catalog(client: httpx.AsyncClient) -> tuple[list[LibraryEntry], int]:
    """Entries of every published release, newest first, and the number of unreadable profiles.json files."""
    try:
        response = await client.get(RELEASES_URL, params={"per_page": 100}, headers=_HEADERS, timeout=20.0)
    except httpx.HTTPError as exc:
        raise _unreachable(str(exc) or type(exc).__name__) from exc
    if response.status_code // 100 != 2:
        raise _list_error(response)
    try:
        releases = response.json()
    except ValueError as exc:
        raise _unreachable("the answer is not JSON") from exc
    if not isinstance(releases, list):
        raise _unreachable("the answer is not a list of releases")

    published = [r for r in releases if isinstance(r, dict) and not r.get("draft")]
    entries: list[LibraryEntry] = []
    seen: set[str] = set()
    skipped = 0
    for release in sorted(published, key=_newest_first):
        asset = _assets(release).get(PROFILES_NAME)
        if asset is None or not asset.get("browser_download_url"):
            continue
        raw = await _profiles_bytes(client, str(asset["browser_download_url"]))
        try:
            if raw is None:
                raise LibraryError("profiles.json could not be downloaded")
            found = parse_profiles(raw, release)
        except LibraryError:
            skipped += 1
            continue
        for entry in found:
            if entry.sha256 not in seen:
                seen.add(entry.sha256)
                entries.append(entry)
    return entries, skipped
