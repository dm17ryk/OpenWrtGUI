"""Services (v0.6b plan D6): every init script `rc list` shows. The app's own path offers restart only, never
stop or disable: without it the app (or the LuCI bridge, or the Logs tab) loses the router."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openwrtgui.system.parse import RcService

PROTECTED: dict[str, str] = {
    "dropbear": "This app reaches the router over SSH (dropbear): stopping or disabling it cuts the app off",
    "rpcd": "The app's settings changes and the LuCI pages go through rpcd",
    "uhttpd": "LuCI pages open through uhttpd",
    "network": "network carries this app's connection to the router",
    "firewall": "Stopping the firewall drops the router's rules; restart applies them again",
    "log": "The Logs tab reads the system log from log (logd)",
}
# a restart of these reloads the router's network or Wi-Fi: the txctl session must be told (AGENTS.md)
NETWORK_RELOAD = frozenset({"network", "firewall", "wpad", "dnsmasq"})


class ServiceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    enabled: bool
    running: bool
    start: int | None
    stop: int | None
    protected: str | None  # why only restart is offered; None: every action is


def service_rows(rc: list[RcService]) -> list[ServiceRow]:
    return [
        ServiceRow(
            name=r.name,
            enabled=r.enabled,
            running=r.running,
            start=r.start,
            stop=r.stop,
            protected=PROTECTED.get(r.name),
        )
        for r in rc
    ]
