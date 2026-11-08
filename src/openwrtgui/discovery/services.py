"""Custom services (decision D10): an init script from a custom package or added after flashing. Its state
comes from procd (`service list`) and `/etc/init.d/<name> enabled`; every other service waits for v0.6."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.transport.base import Transport, ubus_command

SERVICE_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
Action = Literal["start", "stop", "restart"]


class ServiceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source: Literal["custom", "overlay"]
    package: str | None
    running: bool | None
    enabled: bool | None


def _name(name: str) -> str:
    if not SERVICE_NAME.fullmatch(name):
        raise ValueError(f"{name} is not a service name")
    return name


def service_command(name: str, action: Action) -> str:
    return f"/etc/init.d/{_name(name)} {action}"


def enabled_command(name: str) -> str:
    return f"/etc/init.d/{_name(name)} enabled; echo $?"


async def read_service(t: Transport, name: str) -> tuple[bool | None, bool | None]:
    """(running, enabled); None where the router does not say."""
    listed = await t.run(ubus_command("service", "list", {"name": _name(name)}))
    running: bool | None = None
    if listed.ok:
        try:
            data = json.loads(listed.stdout or "{}")
        except ValueError:
            data = None
        if isinstance(data, dict):
            instances = (data.get(name) or {}).get("instances") or {}
            running = any(isinstance(i, dict) and i.get("running") for i in instances.values())
    answer = (await t.run(enabled_command(name))).stdout.strip()
    enabled = {"0": True, "1": False}.get(answer)
    return running, enabled
