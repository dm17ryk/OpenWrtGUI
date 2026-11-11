"""The LuCI bridge follows the router's HTTPS redirect (plan D6): with `redirect_https` on, uhttpd answers
http with a redirect to https, so the bridge talks TLS to the router's loopback port 443 instead."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from openwrtgui.luci_bridge.proxy import BridgeProxy
from openwrtgui.luci_bridge.upstream import router_web, ssh_upstream
from openwrtgui.transport.base import CommandResult

REDIRECT = "uci -q get uhttpd.main.redirect_https"
LISTEN = "uci -q get uhttpd.main.listen_{}"
ALL = {"http": "0.0.0.0:80 [::]:80", "https": "0.0.0.0:443 [::]:443"}


@dataclass
class _Forward:
    port: int

    async def close(self) -> None:
        return None


@dataclass
class FakeT:
    redirect: str | None
    listen: dict[str, str] = field(default_factory=lambda: dict(ALL))
    forwarded: list[tuple[str, int]] = field(default_factory=list)

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        answers = {REDIRECT: self.redirect, **{LISTEN.format(k): v for k, v in self.listen.items()}}
        assert command in answers, command
        answer = answers[command]
        if answer is None:
            return CommandResult(command, "", "uci: Entry not found\n", 1)
        return CommandResult(command, answer + "\n", "", 0)

    async def forward_local(self, host: str, port: int) -> _Forward:
        self.forwarded.append((host, port))
        return _Forward(50000 + port)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        raise NotImplementedError

    async def open_shell(self, cols: int, rows: int):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def close(self) -> None:
        return None


async def test_router_web_follows_redirect_https() -> None:
    assert await router_web(FakeT("1")) == (443, "https")  # type: ignore[arg-type]
    assert await router_web(FakeT("0")) == (80, "http")  # type: ignore[arg-type]
    assert await router_web(FakeT(None)) == (80, "http")  # type: ignore[arg-type]


async def test_the_bridge_uses_the_port_uhttpd_listens_on() -> None:
    """A listen list with another port, as LuCI or a router's own config may set it: the tunnel goes to that
    port on the router's loopback (PR #48 review: it always went to 443 or 80)."""
    custom = {"http": "0.0.0.0:8080 [::]:8080", "https": "0.0.0.0:8443 [::]:8443"}
    assert await router_web(FakeT("1", custom)) == (8443, "https")  # type: ignore[arg-type]
    assert await router_web(FakeT("0", custom)) == (8080, "http")  # type: ignore[arg-type]
    loop_only = {"http": "127.0.0.1:81", "https": "8444"}  # loopback only, and a bare port (every address)
    assert await router_web(FakeT("0", loop_only)) == (81, "http")  # type: ignore[arg-type]
    assert await router_web(FakeT("1", loop_only)) == (8444, "https")  # type: ignore[arg-type]
    v6_only = {"http": "[::]:8080", "https": "[::1]:8443"}  # nothing the IPv4 loopback reaches: the default
    assert await router_web(FakeT("1", v6_only)) == (443, "https")  # type: ignore[arg-type]


async def test_the_bridge_follows_redirect_https() -> None:
    t = FakeT("1")
    upstream = await ssh_upstream(t)  # type: ignore[arg-type]
    assert t.forwarded == [("127.0.0.1", 443)] and upstream.scheme == "https"
    bases: list[str] = []

    def client(base: str) -> httpx.AsyncClient:
        bases.append(base)
        return httpx.AsyncClient(base_url=base)

    proxy = BridgeProxy(
        upstream_port=upstream.port, secret="s", sid="x", scheme=upstream.scheme, client_factory=client
    )
    await proxy.stop()
    # the SSH forward to the router's own loopback is the authentication; its certificate is self-signed
    assert bases == [f"https://127.0.0.1:{upstream.port}"] and proxy.verify is False


async def test_plain_http_stays_checked() -> None:
    t = FakeT("0")
    upstream = await ssh_upstream(t)  # type: ignore[arg-type]
    bases: list[str] = []

    def client(base: str) -> httpx.AsyncClient:
        bases.append(base)
        return httpx.AsyncClient(base_url=base)

    proxy = BridgeProxy(
        upstream_port=upstream.port, secret="s", sid="x", scheme="http", client_factory=client
    )
    await proxy.stop()
    assert t.forwarded == [("127.0.0.1", 80)] and bases == [f"http://127.0.0.1:{upstream.port}"]
    assert proxy.verify is True
