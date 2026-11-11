"""Where a bridge sends LuCI requests: the router's web server through SSH, or the simulator's stand-in."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from openwrtgui.luci_bridge.server import serve
from openwrtgui.transport.base import Forwarder, Transport, TransportError

ROUTER_WEB = ("127.0.0.1", 80)  # uhttpd as the router sees itself
ROUTER_WEB_TLS = ("127.0.0.1", 443)
REDIRECT_HTTPS = "uci -q get uhttpd.main.redirect_https"
LISTEN = "uci -q get uhttpd.main.listen_{}"  # listen_http / listen_https
Scheme = Literal["http", "https"]


def loopback_port(listen: str, default: int) -> int:
    """The port a listen list serves the router's own 127.0.0.1 on: an entry for every IPv4 address, for
    127.0.0.1, or a bare port (every address). An IPv6-only list, or none, gives the default."""
    for entry in listen.split():
        address, sep, port = entry.rpartition(":")
        if port.isdigit() and (not sep or address in ("0.0.0.0", "127.0.0.1")):
            return int(port)
    return default


@dataclass(frozen=True)
class Upstream:
    port: int
    close: Callable[[], Awaitable[None]]
    scheme: Scheme = "http"


async def router_web(t: Transport) -> tuple[int, Scheme]:
    """Where uhttpd serves LuCI to the bridge: with `redirect_https` on it answers plain http with a redirect
    to https, so the bridge goes to uhttpd's HTTPS port and talks TLS (v0.6c D6). The port is the one uhttpd
    listens on for the router's loopback (a router may set 8443 or 8080), else 443 or 80."""
    result = await t.run(REDIRECT_HTTPS)
    scheme: Scheme = "https" if result.ok and result.stdout.strip() == "1" else "http"
    default = ROUTER_WEB_TLS[1] if scheme == "https" else ROUTER_WEB[1]
    listen = await t.run(LISTEN.format(scheme))
    return loopback_port(listen.stdout if listen.ok else "", default), scheme


async def ssh_upstream(t: Transport) -> Upstream:
    if not isinstance(t, Forwarder):
        raise TransportError("This connection cannot forward a port to the router's web server")
    port, scheme = await router_web(t)
    forward = await t.forward_local(ROUTER_WEB[0], port)
    return Upstream(forward.port, forward.close, scheme)


async def sim_upstream(title_of: Callable[[str], str]) -> Upstream:
    """A stand-in for LuCI: one page per path, showing which session cookie arrived."""

    async def page(request: Request) -> HTMLResponse:
        path = request.path_params["path"]
        sid = request.cookies.get("sysauth_http", "none")
        body = f"<h1>LuCI (simulated): {html.escape(title_of(path))}</h1><p>session {html.escape(sid)}</p>"
        return HTMLResponse(body)

    app = Starlette(routes=[Route("/cgi-bin/luci/{path:path}", page, methods=["GET", "POST"])])
    port, stop = await serve(app)
    return Upstream(port, stop)
