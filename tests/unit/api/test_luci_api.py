from __future__ import annotations

import httpx

from openwrtgui.context import AppContext


async def test_luci_api_open_list_close(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    pages = (await authed.get("/api/routers/ap1/luci/pages")).json()
    dhcp = {
        "path": "admin/network/dhcp",
        "title": "DHCP",
        "package": "luci-mod-network",
        "native": "network",  # it has a screen now, and still opens in LuCI on request
        "section": "Network",
        "label": "Network › DHCP",
        "available": True,
        "missing": None,
        "checked": True,
    }
    assert dhcp in pages
    view = (await authed.post("/api/routers/ap1/luci/open", json={"path": "admin/network/dhcp"})).json()
    assert view["access"] == "write" and view["url"].startswith("http://127.0.0.1:") and view["page"] == dhcp
    assert (await authed.get(f"/api/routers/ap1/luci/bridges/{view['id']}/changes")).json() == []
    assert (await authed.get(f"/api/routers/ap1/luci/bridges/{view['id']}")).json() == view
    closed = (await authed.post(f"/api/routers/ap1/luci/bridges/{view['id']}/close")).json()
    assert closed == {"id": view["id"], "changes": []}
    assert (await authed.post(f"/api/routers/ap1/luci/bridges/{view['id']}/close")).status_code == 404
    assert (await authed.get(f"/api/routers/ap1/luci/bridges/{view['id']}")).status_code == 404
    await ctx.luci.close_all()


async def test_luci_api_unknown_page_is_422(authed: httpx.AsyncClient) -> None:
    r = await authed.post("/api/routers/ap1/luci/open", json={"path": "admin/nope"})
    assert r.status_code == 422 and r.json()["detail"] == "No LuCI page admin/nope on AP1 · bench"


async def test_hidden_page_opens_with_422(authed: httpx.AsyncClient) -> None:
    r = await authed.post("/api/routers/ap1/luci/open", json={"path": "admin/system/mounts"})
    assert r.status_code == 422 and r.json()["detail"].endswith("needs /sbin/block")
    pages = (await authed.get("/api/routers/ap1/luci/pages")).json()
    assert next(p for p in pages if p["path"] == "admin/system/mounts")["available"] is False
