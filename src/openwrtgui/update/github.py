"""Read releases from the public GitHub repo (anonymous).

When the API's hourly budget for this network is used up, the release pages are read instead (github_pages).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

from openwrtgui.github_pages import TIMEOUT, PageRelease, releases_from_pages, reset_time, used_up
from openwrtgui.update.versions import Version, parse_version
from openwrtgui.version import APP_VERSION

RELEASES_URL = "https://api.github.com/repos/dm17ryk/OpenWrtGUI/releases"
RELEASES_PAGE = "https://github.com/dm17ryk/OpenWrtGUI/releases"
SUMS_NAME = "SHA256SUMS.txt"
_HEADERS = {"User-Agent": f"OpenWrtGUI/{APP_VERSION}"}


class RateLimited(Exception):
    """GitHub's API budget for this network is used up, and the release pages did not answer either."""

    def __init__(self, reset: datetime | None) -> None:
        super().__init__("GitHub's hourly limit for this network is used up")
        self.reset = reset


@dataclass(frozen=True)
class Release:
    version: Version
    tag: str
    name: str
    notes: str
    prerelease: bool
    published_at: datetime | None
    installer_name: str
    installer_url: str
    installer_size: int
    sums_url: str
    url: str


def _page(tag: str) -> str:
    return f"{RELEASES_PAGE}/tag/{tag}"


def _release(raw: dict[str, Any]) -> Release | None:
    try:
        version = parse_version(str(raw.get("tag_name", "")))
    except ValueError:
        return None
    assets = {a.get("name"): a for a in raw.get("assets", [])}
    installer = assets.get(f"OpenWrtGUI-Setup-{version}.exe")
    sums = assets.get(SUMS_NAME)
    if not installer or not sums:
        return None
    published = raw.get("published_at")
    return Release(
        version=version,
        tag=str(raw["tag_name"]),
        name=str(raw.get("name") or raw["tag_name"]),
        notes=str(raw.get("body") or ""),
        prerelease=bool(raw.get("prerelease")),
        published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
        installer_name=str(installer["name"]),
        installer_url=str(installer["browser_download_url"]),
        installer_size=int(installer.get("size", 0)),
        sums_url=str(sums["browser_download_url"]),
        url=str(raw.get("html_url") or _page(str(raw["tag_name"]))),
    )


def _from_page(page: PageRelease) -> Release | None:
    """A release the pages list: the release workflow names its two assets, so their URLs follow the tag."""
    try:
        version = parse_version(page.tag)
    except ValueError:
        return None
    installer = f"OpenWrtGUI-Setup-{version}.exe"
    return Release(
        version=version,
        tag=page.tag,
        name=f"OpenWrtGUI {version}",
        notes="",
        prerelease=version.ci is not None,
        published_at=page.updated,
        installer_name=installer,
        installer_url=f"{RELEASES_PAGE}/download/{page.tag}/{installer}",
        installer_size=0,
        sums_url=f"{RELEASES_PAGE}/download/{page.tag}/{SUMS_NAME}",
        url=_page(page.tag),
    )


async def fetch_releases(client: httpx.AsyncClient) -> list[Release]:
    response = await client.get(
        RELEASES_URL,
        params={"per_page": 30},
        headers={"Accept": "application/vnd.github+json", **_HEADERS},
        timeout=TIMEOUT,
    )
    if used_up(response):
        try:
            pages = await releases_from_pages(client, RELEASES_PAGE, _HEADERS)
        except (httpx.HTTPError, ValueError) as exc:
            raise RateLimited(reset_time(response)) from exc
        return [r for r in (_from_page(p) for p in pages) if r is not None]
    response.raise_for_status()
    return [r for r in (_release(raw) for raw in response.json()) if r is not None]


def pick_release(
    releases: list[Release],
    channel: Literal["stable", "prerelease"],
    current: Version,
    skipped: str | None,
) -> Release | None:
    candidates = [
        r
        for r in releases
        if (channel == "prerelease" or not r.prerelease) and r.version > current and str(r.version) != skipped
    ]
    return max(candidates, key=lambda r: r.version, default=None)
