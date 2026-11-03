"""Read releases from the public GitHub repo (anonymous)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

from openwrtgui.update.versions import Version, parse_version
from openwrtgui.version import APP_VERSION

RELEASES_URL = "https://api.github.com/repos/dm17ryk/OpenWrtGUI/releases"
SUMS_NAME = "SHA256SUMS.txt"


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
    )


async def fetch_releases(client: httpx.AsyncClient) -> list[Release]:
    response = await client.get(
        RELEASES_URL,
        params={"per_page": 30},
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"OpenWrtGUI/{APP_VERSION}"},
        timeout=20.0,
    )
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
