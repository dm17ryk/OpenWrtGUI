"""Image library API: list, filter, refresh and download images read from the releases of dm17ryk/openwrt."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext

BOARD = "dlink,dwr-921-c3-uboot"
REVISION = "r35692-b8bffeefdf"
UNKNOWN = "0" * 64


async def _first(authed: httpx.AsyncClient) -> dict[str, object]:
    entries = (await authed.get("/api/images/library")).json()["entries"]
    assert len(entries) == 1
    return dict(entries[0])


async def test_the_library_lists_the_sim_image(authed: httpx.AsyncClient) -> None:
    r = await authed.get("/api/images/library")
    assert r.status_code == 200
    body = r.json()
    assert (body["skipped"], body["error"]) == (0, None)
    assert body["read_at"] is not None
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert (entry["board"], entry["revision"], entry["image_name"]) == (BOARD, REVISION, "mini-r35692.bin")
    assert entry["release_name"] == "Simulated bench firmware"
    assert entry["imported"] is False


async def test_the_board_and_revision_filter(authed: httpx.AsyncClient) -> None:
    both = await authed.get("/api/images/library", params={"board": BOARD, "revision": REVISION})
    assert len(both.json()["entries"]) == 1
    other = await authed.get("/api/images/library", params={"board": BOARD, "revision": "r1-aaaaaaaaaa"})
    assert other.json()["entries"] == []
    assert (await authed.get("/api/images/library", params={"board": "nope"})).json()["entries"] == []


async def test_download_imports_and_marks_it_imported(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    sha = str((await _first(authed))["sha256"])
    r = await authed.post(f"/api/images/library/{sha}")
    assert r.status_code == 200
    assert r.json()["origin"] == (await _first(authed))["release_url"]
    assert [p.key.sha256 for p in ctx.profiles.list()] == [sha]
    assert (await _first(authed))["imported"] is True
    listed = (await authed.get("/api/images")).json()
    assert [p["origin"] for p in listed] == [r.json()["origin"]]


async def test_download_clears_the_dashboard_summaries(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    sha = str((await _first(authed))["sha256"])
    await ctx.discovery.summary("ap1")
    assert "ap1" in ctx.discovery.summaries
    await authed.post(f"/api/images/library/{sha}")
    assert ctx.discovery.summaries == {}


async def test_an_unknown_image_is_404(authed: httpx.AsyncClient) -> None:
    r = await authed.post(f"/api/images/library/{UNKNOWN}")
    assert (r.status_code, r.json()["detail"]) == (404, "No image 000000000000 in the image library")


async def test_a_malformed_hash_is_not_a_route(authed: httpx.AsyncClient) -> None:
    assert (await authed.post("/api/images/library/ABC")).status_code == 422


async def test_a_second_download_is_422(authed: httpx.AsyncClient) -> None:
    sha = str((await _first(authed))["sha256"])
    assert (await authed.post(f"/api/images/library/{sha}")).status_code == 200
    again = await authed.post(f"/api/images/library/{sha}")
    assert again.status_code == 422
    assert again.json()["detail"].startswith("This image is already imported")


async def test_refresh_reads_again(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    first = (await authed.get("/api/images/library")).json()["read_at"]
    r = await authed.post("/api/images/library/refresh")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 1
    assert body["read_at"] >= first


async def test_the_discovery_read_never_asks_github(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.library, "_client_factory", lambda: pytest.fail("Discovery asked GitHub"))
    assert (await authed.get("/api/routers/ap1/discovery")).status_code == 200


async def test_the_library_works_while_bench_guard_sees_a_run(authed_guard_live: httpx.AsyncClient) -> None:
    r = await authed_guard_live.get("/api/images/library")
    assert r.status_code == 200
    sha = r.json()["entries"][0]["sha256"]
    assert (await authed_guard_live.post(f"/api/images/library/{sha}")).status_code == 200


async def test_the_library_needs_the_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/images/library")).status_code == 401
