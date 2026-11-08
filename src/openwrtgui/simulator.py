"""Router simulator: replay transports built from AP2 recordings plus per-router overlays."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncssh
import httpx

from openwrtgui.guard.bench_guard import ProcessInfo
from openwrtgui.simfw import SimFirewall
from openwrtgui.simimage import SimImage
from openwrtgui.simnet import SimNetwork
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
    """The wizard's Connector for simulated routers, found by the address they answer on now: the one in
    routers.json, or lan's address once a change moved it. One host key per router, at any address."""

    def __init__(self, sim_dir: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._sim_dir = sim_dir
        self._clock = clock
        self._entries = sim_routers(sim_dir)
        self._states: dict[str, SimState] = {}
        self._host_keys: dict[tuple[str, int], HostKeyInfo] = {}

    def _address(self, entry: dict[str, Any]) -> str:
        state = self._states.get(entry["id"])
        if state is not None and state.image is not None and state.image.address_reset:
            return "192.168.1.1"  # back like firstboot after a flash without settings
        if state is not None and state.net is not None:
            return state.net.address() or entry["host"]
        return str(entry["host"])

    def _entry(self, host: str) -> dict[str, Any]:
        for entry in self._entries:
            if self._address(entry) == host:
                state = self._states.get(entry["id"])
                if state is not None and state.image is not None and state.image.rebooting:
                    raise Unreachable(f"{host}:22: Connection refused")
                if state is not None and state.net is not None and not state.net.reachable():
                    raise Unreachable(f"{host}:22: No route to host")
                return entry
        raise Unreachable(f"{host}:22: no simulated router at this address")

    def _new_state(self, entry: dict[str, Any]) -> SimState:
        wifi = net = None
        last = int(str(entry["host"]).rsplit(".", 1)[1])
        if entry.get("wifi"):
            text = (self._sim_dir / "wifi" / entry["wifi"]).read_text(encoding="utf-8")
            wifi = SimWifi(text, bssid=f"02:00:00:00:00:{last:02x}")
        if entry.get("net"):
            text = (self._sim_dir / "net" / entry["net"]).read_text(encoding="utf-8")
            leases = [tuple(lease) for lease in entry.get("leases", [])]
            net = SimNetwork(
                text, leases=leases, wifi_mirror=bool(entry.get("wifi_mirror")), clock=self._clock
            )
        fw = None
        if net is not None:
            runtime = (
                json.loads((self._sim_dir / "fw" / entry["fw"]).read_text(encoding="utf-8"))
                if entry.get("fw")
                else {}
            )
            fw = SimFirewall(net, runtime, clock=self._clock)
        image = None
        if entry.get("image"):
            upper = (
                json.loads((self._sim_dir / entry["upper"]).read_text(encoding="utf-8"))
                if entry.get("upper")
                else {}
            )
            board = sim_commands(self._sim_dir, entry["id"]).get("ubus call system board")
            image = SimImage(
                (self._sim_dir.parent / "images" / entry["image"]).read_bytes(),
                upper,
                clock=self._clock,
                board_json=board.stdout if board is not None else None,
            )
        return SimState(
            root_password=entry.get("password") or SIM_ROOT_PASSWORD, wifi=wifi, net=net, fw=fw, image=image
        )

    def state(self, host: str) -> SimState:
        entry = self._entry(host)
        if entry["id"] not in self._states:
            self._states[entry["id"]] = self._new_state(entry)
        state = self._states[entry["id"]]
        if state.image is not None and state.image.generation != state.generation_seen:
            # flashed without keeping settings: no app key, no password, as at firstboot
            state.generation_seen = state.image.generation
            state.authorized_keys.clear()
            state.root_password = None
        return state

    def _generation(self, router_id: str) -> int:
        state = self._states.get(router_id)
        return state.image.generation if state is not None and state.image is not None else 0

    async def fetch_host_key(self, host: str, port: int = 22) -> HostKeyInfo:
        router_id = self._entry(host)["id"]
        key_id = (router_id, self._generation(router_id))  # a reflash without settings makes a new host key
        if key_id not in self._host_keys:
            key = asyncssh.generate_private_key("ssh-ed25519")
            self._host_keys[key_id] = HostKeyInfo(
                type="ssh-ed25519",
                fingerprint=key.get_fingerprint("sha256"),
                public=key.export_public_key("openssh").decode("ascii").strip(),
            )
        return self._host_keys[key_id]

    async def identity_unchecked(self, host: str, port: int = 22) -> tuple[str, str]:
        """As the real connector: root with no password, the host key not checked (the sim checks none)."""
        from openwrtgui.onboard.wizard import identity_of

        try:
            t = await self.connect(host, port, password=None, key_paths=[])
            release = (await t.run("cat /etc/openwrt_release")).stdout
            board = (await t.run("ubus call system board")).stdout
        except (AuthFailed, Unreachable):
            return "", ""
        return identity_of(release, board)

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
            trusted = entry.get("auth") == "key" and self._generation(entry["id"]) == 0
            if not trusted and not any(line in state.authorized_keys for line in _public_lines(key_paths)):
                raise AuthFailed(f"{host} refused the key")
        else:
            raise AuthFailed(f"{host} refused the login")
        return ReplayTransport(sim_commands(self._sim_dir, entry["id"]), state=state)
