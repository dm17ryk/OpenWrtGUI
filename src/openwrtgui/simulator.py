"""Router simulator: replay transports built from AP2 recordings plus per-router overlays."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncssh
import httpx

from openwrtgui.guard.bench_guard import ProcessInfo
from openwrtgui.simwifi import SimWifi
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import (
    AuthFailed,
    CommandResult,
    HostKeyInfo,
    KeyFileError,
    Transport,
    Unreachable,
)
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


SIM_GUARD_ENV = "OPENWRTGUI_SIM_GUARD"
SIM_RUN = ProcessInfo(
    18244, ("python.exe", r"D:\Essence_SC\wifi_ref\dima_night.py"), datetime(2026, 11, 3, 21, 4)
)


def sim_process_lister() -> list[ProcessInfo]:
    """With OPENWRTGUI_SIM_GUARD=live the simulator pretends dima_night.py is running."""
    return [SIM_RUN] if os.environ.get(SIM_GUARD_ENV) == "live" else []


def seed_routers(sim_dir: Path, store: RouterStore) -> None:
    for entry in sim_routers(sim_dir):
        if entry.get("wizard_only") or store.get(entry["id"]) is not None:
            continue
        store.upsert(
            RouterRecord(
                id=entry["id"],
                name=entry["name"],
                host=entry["host"],
                auth=entry["auth"],
                added_at=datetime(2026, 11, 3, 9, 0),
            )
        )


def sim_http_client(sim_dir: Path) -> httpx.AsyncClient:
    """GitHub stand-in for the updater: serves tests/fixtures/github/releases.json."""
    releases = json.loads((sim_dir.parent / "github" / "releases.json").read_text(encoding="utf-8"))

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=releases)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _public_lines(key_paths: Sequence[Path]) -> list[str]:
    lines = []
    for path in key_paths:
        try:
            lines.append(Path(f"{path}.pub").read_text(encoding="utf-8").strip())
        except OSError as exc:  # as SshTransport does for a key file it cannot load
            raise KeyFileError(str(path), str(exc)) from exc
    return lines


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
            wifi = None
            if entry.get("wifi"):
                text = (self._sim_dir / "wifi" / entry["wifi"]).read_text(encoding="utf-8")
                wifi = SimWifi(text, bssid=f"02:00:00:00:00:{int(host.rsplit('.', 1)[1]):02x}")
            self._states[host] = SimState(root_password=entry.get("password") or SIM_ROOT_PASSWORD, wifi=wifi)
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
        self,
        host: str,
        port: int,
        *,
        password: str | None,
        key_paths: Sequence[Path],
        username: str = "root",
        prove: bool = False,
    ) -> Transport:
        entry = self._entry(host)
        state = self.state(host)
        if state.root_password is None:
            # Like dropbear with an empty root password: anyone gets in without being checked,
            # which a login that must prove itself (asyncssh disable_trivial_auth) refuses.
            if prove:
                raise AuthFailed(f"{host} let the login in without checking it")
        elif password is not None:
            if password != state.root_password:
                raise AuthFailed(f"{host} refused the login")
        elif key_paths:
            if entry.get("auth") != "key" and not any(
                line in state.authorized_keys for line in _public_lines(key_paths)
            ):
                raise AuthFailed(f"{host} refused the key")
        else:
            raise AuthFailed(f"{host} refused the login")
        return ReplayTransport(sim_commands(self._sim_dir, entry["id"]), state=state)
