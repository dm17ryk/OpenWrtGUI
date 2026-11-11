"""The loopback proxy a LuCI tab talks to. Only the app's own tab gets in (bridge cookie); LuCI gets the
rpcd session cookie added on the way, so no password is ever typed."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from openwrtgui.luci_bridge.server import serve

BRIDGE_COOKIE = "owg_bridge"
ENTER_PATHS = ("/cgi-bin/luci", "/luci-static")
NOT_YOURS = "This page belongs to OpenWrtGUI's LuCI bridge."
LOST = "Lost the SSH connection to the router. Close this page and open it again."
METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
_DROP_REQUEST = _HOP | {"host", "cookie", "content-length"}
_DROP_RESPONSE = _HOP | {"content-length", "content-encoding", "x-frame-options"}


def _keep_response_header(name: str, value: str) -> bool:
    name = name.lower()
    if name in _DROP_RESPONSE:
        return False
    if name == "set-cookie" and value.lstrip().lower().startswith("sysauth"):
        return False
    return not (name == "content-security-policy" and "frame-ancestors" in value)


class BridgeProxy:
    def __init__(
        self,
        *,
        upstream_port: int,
        secret: str,
        sid: str,
        client_factory: Callable[[str], httpx.AsyncClient] | None = None,
        on_use: Callable[[], None] = lambda: None,
        scheme: Literal["http", "https"] = "http",
    ) -> None:
        self._secret = secret
        self._sid = sid
        self._on_use = on_use
        # With the router's HTTPS redirect on, the bridge talks TLS to the router's own port 443 through the
        # SSH forward. The certificate is the router's self-signed one and is not checked: the SSH tunnel,
        # with its pinned host key, is what proves this is the router.
        self.verify = scheme == "http"
        verify = self.verify
        make = client_factory or (lambda base: httpx.AsyncClient(base_url=base, timeout=30.0, verify=verify))
        self._client = make(f"{scheme}://127.0.0.1:{upstream_port}")
        self._stop: Callable[[], Awaitable[None]] | None = None
        self.app = Starlette(
            routes=[
                Route("/__owg/enter", self._enter, methods=["GET"]),
                Route("/{path:path}", self._forward, methods=METHODS),
            ]
        )

    def set_sid(self, sid: str) -> None:
        self._sid = sid

    async def start(self) -> int:
        port, self._stop = await serve(self.app)
        return port

    async def stop(self) -> None:
        if self._stop is not None:
            await self._stop()
            self._stop = None
        await self._client.aclose()

    async def _enter(self, request: Request) -> Response:
        if not secrets.compare_digest(request.query_params.get("k", ""), self._secret):
            return PlainTextResponse(NOT_YOURS, status_code=403)
        to = request.query_params.get("to", "/cgi-bin/luci/")
        if not to.startswith(ENTER_PATHS):
            return PlainTextResponse("Only LuCI pages open here.", status_code=400)
        response = RedirectResponse(to, status_code=303)
        response.set_cookie(BRIDGE_COOKIE, self._secret, httponly=True, samesite="strict", path="/")
        return response

    async def _forward(self, request: Request) -> Response:
        if not secrets.compare_digest(request.cookies.get(BRIDGE_COOKIE, ""), self._secret):
            return PlainTextResponse(NOT_YOURS, status_code=403)
        self._on_use()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST}
        # LuCI reads sysauth_https over TLS, sysauth_http otherwise
        name = "sysauth_http" if self.verify else "sysauth_https"
        headers["cookie"] = f"{name}={self._sid}; sysauth={self._sid}"
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        try:
            upstream = await self._client.request(
                request.method, target, headers=headers, content=await request.body()
            )
        except httpx.HTTPError:
            return PlainTextResponse(LOST, status_code=502)
        response = Response(content=upstream.content, status_code=upstream.status_code)
        for name, value in upstream.headers.multi_items():
            if _keep_response_header(name, value):
                response.raw_headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
        return response
