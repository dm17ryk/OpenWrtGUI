"""Services (v0.6b plan D6): every init script `rc list` shows. The app's own path offers restart only, never
stop or disable: without it the app (or the LuCI bridge, or the Logs tab) loses the router."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openwrtgui.system import commands as s
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
RESTART_ONLY: frozenset[s.ServiceAction] = frozenset({"stop", "disable"})
SETTLE_S = 10.0  # procd starts and stops a service within this (D6 proof window)
RC_LOCAL_END = "The last line of rc.local is exit 0: the boot waits for it"


def network_warning(router_name: str) -> str:
    return (
        f"This restarts {router_name}'s network: devices and this app lose {router_name} for a few seconds; "
        "the txctl session must be told"
    )


def check_action(row: RcService | None, name: str, action: s.ServiceAction, router_name: str) -> str:
    """The init script command for an action the screen offers; refused before anything is sent."""
    command = s.init(name, action)  # checks the name and the action
    if row is None:
        raise ValueError(f"{name} is not an init script on {router_name}")
    if name in PROTECTED and action in RESTART_ONLY:
        raise ValueError(f"Only restart is offered for {name}: {PROTECTED[name]}")
    return command


def action_warnings(name: str, action: s.ServiceAction, router_name: str) -> tuple[str, ...]:
    if name in NETWORK_RELOAD and action in ("start", "stop", "restart"):
        return (network_warning(router_name),)
    return ()


def action_holds(row: RcService | None, action: s.ServiceAction) -> tuple[bool, str]:
    """(done, detail): what `rc list` shows of an action once it ran."""
    if row is None:
        return False, "gone from rc list"
    if action in ("enable", "disable"):
        return row.enabled is (action == "enable"), "enabled" if row.enabled else "disabled"
    if not row.instance:
        return True, "ran (runs once: procd keeps no instance of it)"
    return row.running is (action != "stop"), "running" if row.running else "not running"


def check_rc_local(text: str) -> str:
    """The file as written (one newline at its end): rc.local ends with `exit 0`, as LuCI's template."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[-1].strip() != "exit 0":
        raise ValueError(RC_LOCAL_END)
    return text.rstrip("\n") + "\n"


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
