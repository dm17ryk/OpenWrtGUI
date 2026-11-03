"""Router simulator: replay transports built from AP2 recordings plus per-router overlays."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import asyncssh

from openwrtgui.transport.base import AuthFailed, CommandResult, HostKeyInfo, Transport, Unreachable
from openwrtgui.transport.fake import ReplayTransport, SimState, load_commands

SIM_ROOT_PASSWORD = "set-on-router"


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


def _public_lines(key_paths: Sequence[Path]) -> list[str]:
    return [Path(f"{p}.pub").read_text(encoding="utf-8").strip() for p in key_paths]


class SimConnector:
    """The wizard's Connector for simulated routers (looked up by host in routers.json)."""

    def __init__(self, sim_dir: Path) -> None:
        self._sim_dir = sim_dir
        self._entries = {e["host"]: e for e in sim_routers(sim_dir)}
        self._states: dict[str, SimState] = {}
        self._host_keys: dict[str, HostKeyInfo] = {}

    def _entry(self, host: str) -> dict[str, Any]:
        entry = self._entries.get(host)
        if entry is None:
            raise Unreachable(f"{host}:22: no simulated router at this address")
        return entry

    def state(self, host: str) -> SimState:
        if host not in self._states:
            entry = self._entry(host)
            self._states[host] = SimState(root_password=entry.get("password") or SIM_ROOT_PASSWORD)
        return self._states[host]

    async def fetch_host_key(self, host: str, port: int = 22) -> HostKeyInfo:
        self._entry(host)
        if host not in self._host_keys:
            key = asyncssh.generate_private_key("ssh-ed25519")
            self._host_keys[host] = HostKeyInfo(
                type="ssh-ed25519",
                fingerprint=key.get_fingerprint("sha256"),
                public=key.export_public_key("openssh").decode("ascii").strip(),
            )
        return self._host_keys[host]

    async def connect(
        self, host: str, port: int, *, password: str | None, key_paths: Sequence[Path]
    ) -> Transport:
        entry = self._entry(host)
        state = self.state(host)
        if password is not None:
            if state.root_password is not None and password != state.root_password:
                raise AuthFailed(f"{host} refused the login")
        elif key_paths:
            if entry.get("auth") != "key" and not any(
                line in state.authorized_keys for line in _public_lines(key_paths)
            ):
                raise AuthFailed(f"{host} refused the key")
        else:
            raise AuthFailed(f"{host} refused the login")
        return ReplayTransport(sim_commands(self._sim_dir, entry["id"]), state=state)
