"""Bench Guard: while a harness run is live, every router is read-only (spec section 6)."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Literal

import psutil

from openwrtgui.store.settings import GuardWatchList

ReasonKind = Literal["lock_file", "process", "router_ssid", "router_process"]


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    cmdline: tuple[str, ...]
    started: datetime


@dataclass(frozen=True)
class GuardReason:
    kind: ReasonKind
    detail: str
    since: datetime | None
    router: str | None
    pid: int | None = None

    @property
    def text(self) -> str:
        since = f"{self.since:%H:%M}" if self.since else "?"
        if self.kind == "process":
            return f"{self.detail} started {since} (PID {self.pid})"
        if self.kind == "lock_file":
            return f"Lock file {self.detail} present since {since}"
        if self.kind == "router_ssid":
            return f"SSID {self.detail} on air on {self.router}"
        return f"{self.detail} running on {self.router}"


@dataclass(frozen=True)
class GuardState:
    live: bool
    reasons: tuple[GuardReason, ...]
    checked_at: datetime


class GuardLocked(Exception):
    def __init__(self, state: GuardState) -> None:
        super().__init__(state.reasons[0].text if state.reasons else "Bench Guard: read-only")
        self.state = state


ProcessLister = Callable[[], Iterable[ProcessInfo]]


def psutil_lister() -> Iterable[ProcessInfo]:
    for proc in psutil.process_iter():
        try:
            cmdline = tuple(proc.cmdline())
            started = datetime.fromtimestamp(proc.create_time())
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        if cmdline:
            yield ProcessInfo(proc.pid, cmdline, started)


def _basename(arg: str) -> str:
    return PureWindowsPath(arg).name


def scan_processes(patterns: Sequence[str], lister: ProcessLister = psutil_lister) -> list[GuardReason]:
    found: list[GuardReason] = []
    lowered = [p.lower() for p in patterns]
    for proc in lister():
        for arg in proc.cmdline:
            name = _basename(arg)
            if any(fnmatch.fnmatchcase(name.lower(), p) for p in lowered):
                found.append(GuardReason("process", name, proc.started, None, proc.pid))
                break
    return found


@dataclass
class _RouterSigns:
    ssids: tuple[str, ...] = ()
    processes: tuple[str, ...] = ()


@dataclass
class BenchGuard:
    watch: GuardWatchList
    lister: ProcessLister = psutil_lister
    clock: Callable[[], datetime] = datetime.now
    use_lock_files: bool = True
    _signs: dict[str, _RouterSigns] = field(default_factory=dict)
    _state: GuardState | None = None

    def update_watch(self, watch: GuardWatchList) -> None:
        self.watch = watch

    def set_router_signs(
        self, router_id: str, ssids_on_air: Sequence[str], process_lines: Sequence[str] = ()
    ) -> None:
        self._signs[router_id] = _RouterSigns(tuple(ssids_on_air), tuple(process_lines))

    def forget_router(self, router_id: str) -> None:
        """Drop a removed router's signs (an unreachable router keeps its last ones: fail closed)."""
        self._signs.pop(router_id, None)

    def _router_reasons(self) -> list[GuardReason]:
        reasons: list[GuardReason] = []
        for router_id, signs in sorted(self._signs.items()):
            for ssid in signs.ssids:
                if ssid in self.watch.router_ssids:
                    reasons.append(GuardReason("router_ssid", ssid, None, router_id))
            for line in signs.processes:
                for pattern in self.watch.router_processes:
                    if fnmatch.fnmatch(line, f"*{pattern}*"):
                        reasons.append(GuardReason("router_process", pattern, None, router_id))
        return reasons

    def check_local(self) -> GuardState:
        reasons: list[GuardReason] = []
        for lock in self.watch.lock_files if self.use_lock_files else ():
            path = Path(lock)
            if path.exists():
                since = datetime.fromtimestamp(path.stat().st_mtime)
                reasons.append(GuardReason("lock_file", lock, since, None))
        reasons.extend(scan_processes(self.watch.processes, self.lister))
        reasons.extend(self._router_reasons())
        self._state = GuardState(bool(reasons), tuple(reasons), self.clock())
        return self._state

    def state(self) -> GuardState:
        return self._state if self._state is not None else self.check_local()

    def require_clear(self) -> None:
        state = self.state()
        if state.live:
            raise GuardLocked(state)
