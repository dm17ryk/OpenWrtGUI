"""Images API: import a sysupgrade image (raw body), list and delete profiles, build one from /rom."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from openwrtgui.api import images_api
from openwrtgui.context import AppContext

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"


def _headers(name: str) -> dict[str, str]:
    return {"Content-Type": "application/octet-stream", "X-File-Name": name}


async def test_import_list_delete(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    r = await authed.post("/api/images", content=MINI.read_bytes(), headers=_headers("mini-r35692.bin"))
    assert r.status_code == 200
    body = r.json()
    assert body["custom"] == ["dwr921-diag", "dwr921-internet-led", "dwr921-portctl"]
    assert (body["label"], body["source"], body["packages"]) == (
        "dlink,dwr-921-c3-uboot r35692-b8bffeefdf",
        "image",
        7,
    )
    listed = (await authed.get("/api/images")).json()
    assert [p["label"] for p in listed] == ["dlink,dwr-921-c3-uboot r35692-b8bffeefdf"]
    gone = await authed.delete(f"/api/images/{body['key']['board']}/{body['folder']}")
    assert gone.status_code == 204
    assert (await authed.get("/api/images")).json() == []
    assert (await authed.delete(f"/api/images/{body['key']['board']}/{body['folder']}")).status_code == 404


async def test_import_clears_the_dashboard_summaries(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await ctx.discovery.summary("ap1")
    assert "ap1" in ctx.discovery.summaries
    await authed.post("/api/images", content=MINI.read_bytes(), headers=_headers("mini-r35692.bin"))
    assert ctx.discovery.summaries == {}


async def test_import_errors(authed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    junk = await authed.post("/api/images", content=b"\0" * 4096, headers=_headers("x.bin"))
    assert (junk.status_code, junk.json()["detail"]) == (422, "No squashfs root file system in x.bin")
    await authed.post("/api/images", content=MINI.read_bytes(), headers=_headers("mini-r35692.bin"))
    again = await authed.post("/api/images", content=MINI.read_bytes(), headers=_headers("again.bin"))
    assert again.status_code == 422
    assert again.json()["detail"].startswith("This image is already imported")
    named = await authed.post("/api/images", content=b"x", headers=_headers("../x;y.bin"))
    assert named.status_code == 422
    monkeypatch.setattr(images_api, "MAX_UPLOAD", 1000)
    large = await authed.post("/api/images", content=b"x" * 2000, headers=_headers("big.bin"))
    assert large.status_code == 413


async def test_rom_profile(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    r = await authed.post("/api/routers/ap2/images/rom")
    assert r.status_code == 200
    assert (r.json()["source"], r.json()["label"]) == ("rom", "dlink,dwr-921-c3-uboot r35692-b8bffeefdf")
    state = (await authed.get("/api/routers/ap2/discovery")).json()
    assert state["profile"]["sha256"] == "rom"
    assert (await authed.post("/api/routers/nope/images/rom")).status_code == 404
