"""github_pages.py: release lists read from github.com's pages when the API's hourly budget is used up."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from openwrtgui.github_pages import PageRelease, feed_releases, releases_from_pages, reset_time, used_up

PAGE = "https://github.com/dm17ryk/openwrt/releases"
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:github.com,2008:https://github.com/dm17ryk/openwrt/releases</id>
  <entry>
    <id>tag:github.com,2008:Repository/1323348770/v24.10.8</id>
    <updated>2026-07-24T23:54:19Z</updated>
    <title>v24.10.8</title>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1323348770/../../evil</id>
    <title>a tag that is not a safe path segment</title>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1323348770/v25.12.5</id>
    <updated>2026-10-15T14:50:53Z</updated>
    <title>DWR_921 &amp; qmifix3</title>
  </entry>
</feed>
"""


def _pages(latest: httpx.Response) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == f"{PAGE}/latest":
            return latest
        if str(request.url) == f"{PAGE}.atom":
            return httpx.Response(200, text=FEED)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def test_the_feed_gives_safe_tags_with_titles_and_times() -> None:
    assert feed_releases(FEED) == [
        PageRelease("v24.10.8", "v24.10.8", datetime(2026, 7, 24, 23, 54, 19, tzinfo=UTC)),
        PageRelease("v25.12.5", "DWR_921 & qmifix3", datetime(2026, 10, 15, 14, 50, 53, tzinfo=UTC)),
    ]


async def test_the_latest_release_comes_first_then_the_feed() -> None:
    latest = httpx.Response(302, headers={"Location": f"{PAGE}/tag/v25.12.5"})
    async with _pages(latest) as client:
        found = await releases_from_pages(client, PAGE, {})
    assert [r.tag for r in found] == ["v25.12.5", "v24.10.8"]
    assert found[0].title == "DWR_921 & qmifix3"


@pytest.mark.parametrize(
    "latest",
    [httpx.Response(404), httpx.Response(302, headers={"Location": f"{PAGE}/tag/..%2Fevil"})],
)
async def test_no_usable_latest_release_is_an_error(latest: httpx.Response) -> None:
    async with _pages(latest) as client:
        with pytest.raises(ValueError):
            await releases_from_pages(client, PAGE, {})


def test_used_up_needs_the_rate_limit_headers() -> None:
    assert used_up(httpx.Response(403, headers={"X-RateLimit-Remaining": "0"}))
    assert used_up(httpx.Response(429, headers={"Retry-After": "60"}))
    assert not used_up(httpx.Response(403))
    assert not used_up(httpx.Response(200, headers={"X-RateLimit-Remaining": "0"}))


def test_reset_time_reads_the_epoch_header() -> None:
    assert reset_time(
        httpx.Response(403, headers={"X-RateLimit-Reset": "1800000000"})
    ) == datetime.fromtimestamp(1800000000)
    assert reset_time(httpx.Response(403, headers={"X-RateLimit-Reset": "soon"})) is None
    assert reset_time(httpx.Response(403)) is None
