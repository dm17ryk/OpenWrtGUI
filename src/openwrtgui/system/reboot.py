"""Reboot (v0.6b plan D8): armed by the router-side timer, as flashing starts sysupgrade, so the exec returns
(and the audit gets its exit status) before the router goes down; done only when it answers again with an
uptime younger than the time since it was armed."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.timer import arm_command

# reset and not reset are a reset to defaults' (v0.6c D12): it ends when the router is gone, or is not
RebootPhase = Literal["armed", "waiting", "back", "not back", "reset", "not reset"]
JobKind = Literal["reboot", "restore", "reset"]
TIMER = "reboot"
ARM_S = 2
LIMIT_S = 300.0  # D8: a router that is not back by then needs a person
EVERY_S = 5.0


class RebootBusy(Exception):
    """A reboot of this router is already running (409)."""


class RebootJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    phase: RebootPhase
    started_at: datetime
    kind: JobKind = "reboot"  # one job per router, whatever its kind (409)
    uptime_s: float | None = None  # once back: the fresh uptime that proves the reboot
    detail: str | None = None
    error: str | None = None


def reboot_command() -> str:
    return arm_command(TIMER, ARM_S, ["reboot"])


def reboot_warnings(router_name: str) -> tuple[str, ...]:
    return (
        f"{router_name} is offline for about 60-90 s while it restarts",
        "LTE and Wi-Fi come back with the router; the LuCI bridge and the terminal reconnect by themselves",
    )


def not_back(router_name: str, limit_s: float) -> str:
    return f"{router_name} is not back after {limit_s:g} s: check its power and LEDs, then Reconnect"
