from __future__ import annotations

import httpx

from openwrtgui.luci_bridge.proxy import BRIDGE_COOKIE, BridgeProxy

SECRET = "s3cr3t-bridge"
seen: list[httpx.Request] = []


def _upstream(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    return httpx.Response(
        200,
        html="<h1>LuCI</h1>",
        headers=[
            ("x-frame-options", "SAMEORIGIN"),
            ("set-cookie", "sysauth_http=abc; path=/cgi-bin/luci"),
            ("set-cookie", "other=1; path=/"),
            ("cache-control", "no-cache"),
        ],
    )


def _proxy() -> BridgeProxy:
    seen.clear()
    return BridgeProxy(
        upstream_port=1,
        secret=SECRET,
        sid="SID-1",
        client_factory=lambda base: httpx.AsyncClient(
            base_url=base, transport=httpx.MockTransport(_upstream)
        ),
    )


def _client(proxy: BridgeProxy) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.app), base_url="http://127.0.0.1:9")


async def test_proxy_requires_bridge_cookie() -> None:
    async with _client(_proxy()) as c:
        r = await c.get("/cgi-bin/luci/admin/network/wireless")
        assert r.status_code == 403 and "LuCI bridge" in r.text
        assert (await c.get("/__owg/enter", params={"k": "wrong", "to": "/cgi-bin/luci/"})).status_code == 403
        assert (
            await c.get("/__owg/enter", params={"k": SECRET, "to": "https://evil.example/"})
        ).status_code == 400
        enter = await c.get(
            "/__owg/enter", params={"k": SECRET, "to": "/cgi-bin/luci/admin/network/wireless"}
        )
        assert (
            enter.status_code == 303 and enter.headers["location"] == "/cgi-bin/luci/admin/network/wireless"
        )
        cookie = enter.headers["set-cookie"]
        assert (
            cookie.startswith(f"{BRIDGE_COOKIE}={SECRET}")
            and "HttpOnly" in cookie
            and "SameSite=strict" in cookie
        )
        c.cookies.set(BRIDGE_COOKIE, SECRET)
        page = await c.get("/cgi-bin/luci/admin/network/wireless?x=1")
        assert page.status_code == 200 and "<h1>LuCI</h1>" in page.text
    sent = seen[-1]
    assert sent.url.path == "/cgi-bin/luci/admin/network/wireless" and sent.url.query == b"x=1"
    assert sent.headers["cookie"] == "sysauth_http=SID-1; sysauth=SID-1"


async def test_proxy_strips_frame_headers_and_sysauth_set_cookie() -> None:
    proxy = _proxy()
    async with _client(proxy) as c:
        c.cookies.set(BRIDGE_COOKIE, SECRET)
        page = await c.get("/cgi-bin/luci/")
    assert "x-frame-options" not in page.headers
    assert page.headers.get_list("set-cookie") == ["other=1; path=/"]
    assert page.headers["cache-control"] == "no-cache"


async def test_new_session_id_is_used_after_set_sid() -> None:
    proxy = _proxy()
    proxy.set_sid("SID-2")
    async with _client(proxy) as c:
        c.cookies.set(BRIDGE_COOKIE, SECRET)
        await c.post("/cgi-bin/luci/admin/ubus", content=b'{"x":1}')
    assert (
        seen[-1].headers["cookie"] == "sysauth_http=SID-2; sysauth=SID-2" and seen[-1].content == b'{"x":1}'
    )


async def test_upstream_failure_is_502() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    proxy = BridgeProxy(
        upstream_port=1,
        secret=SECRET,
        sid="SID-1",
        client_factory=lambda base: httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(broken)),
    )
    async with _client(proxy) as c:
        c.cookies.set(BRIDGE_COOKIE, SECRET)
        r = await c.get("/cgi-bin/luci/")
    assert r.status_code == 502 and "Close this page and open it again" in r.text
