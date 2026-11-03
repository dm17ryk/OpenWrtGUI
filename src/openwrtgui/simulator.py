"""Router simulator: replay transports built from AP2 recordings plus per-router overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import load_commands


def sim_routers(sim_dir: Path) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((sim_dir / "routers.json").read_text(encoding="utf-8"))
    return data


def sim_entry(sim_dir: Path, router_id: str) -> dict[str, Any]:
    for entry in sim_routers(sim_dir):
        if entry["id"] == router_id:
            return entry
    raise KeyError(router_id)


def sim_commands(sim_dir: Path, router_id: str) -> dict[str, CommandResult]:
    entry = sim_entry(sim_dir, router_id)
    commands = load_commands(sim_dir.parent / entry["base"] / "commands.json")
    if entry.get("overlay"):
        commands.update(load_commands(sim_dir / entry["overlay"]))
    return commands
