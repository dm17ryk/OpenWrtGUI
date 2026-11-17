"""GitHub's release pages, read when the API's anonymous budget for this network is used up.

GitHub's API allows 60 anonymous requests an hour per public IP address, and every PC behind the same
address shares them. The pages on github.com have no such budget: /releases/latest redirects to the newest
release that is not a pre-release, and releases.atom lists the newest releases. Both the updater and the image
library fall back to them.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime

import httpx

TIMEOUT = 20.0
_SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
_ID = re.compile(r"<id>tag:github\.com,2008:Repository/\d+/([^<\s]+)</id>")
_TITLE = re.compile(r"<title>([^<]*)</title>")
_UPDATED = re.compile(r"<updated>([^<]+)</updated>")
_TAG_PATH = "/releases/tag/"


@dataclass(frozen=True)
class PageRelease:
    """A release as the pages show it: no assets, no notes, no pre-release flag."""

    tag: str
    title: str
    updated: datetime | None


def used_up(response: httpx.Response) -> bool:
    """The API refused because of its rate limit (the hourly budget, or a Retry-After slow-down)."""
    return response.status_code in (403, 429) and (
        response.headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in response.headers
    )


def reset_time(response: httpx.Response) -> datetime | None:
    """When the API's hourly budget refills, in local time, if the response says."""
    try:
        return datetime.fromtimestamp(int(response.headers["X-RateLimit-Reset"]))
    except (KeyError, ValueError, OverflowError, OSError):
        return None


def _time(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def feed_releases(text: str) -> list[PageRelease]:
    """The releases a releases.atom feed lists, in order; a tag that is not a plain name is dropped."""
    found: list[PageRelease] = []
    for block in _ENTRY.findall(text):
        tag = _ID.search(block)
        if tag is None or not _SAFE_TAG.match(tag[1]):
            continue
        title, updated = _TITLE.search(block), _UPDATED.search(block)
        found.append(
            PageRelease(
                tag=tag[1],
                title=html.unescape(title[1]).strip() if title and title[1].strip() else tag[1],
                updated=_time(updated[1]) if updated else None,
            )
        )
    return found


async def releases_from_pages(
    client: httpx.AsyncClient, page: str, headers: dict[str, str]
) -> list[PageRelease]:
    """The newest stable release first, then the rest of the feed. Raises httpx.HTTPError or ValueError."""
    latest = await client.get(f"{page}/latest", headers=headers, timeout=TIMEOUT, follow_redirects=False)
    location = latest.headers.get("Location", "")
    tag = location.rsplit(_TAG_PATH, 1)[1] if latest.is_redirect and _TAG_PATH in location else ""
    if not _SAFE_TAG.match(tag):
        raise ValueError(f"the latest-release page answered {latest.status_code}")
    feed = await client.get(f"{page}.atom", headers=headers, timeout=TIMEOUT)
    feed.raise_for_status()
    listed = feed_releases(feed.text)
    first = next((r for r in listed if r.tag == tag), PageRelease(tag, tag, None))
    return [first, *(r for r in listed if r.tag != tag)]
