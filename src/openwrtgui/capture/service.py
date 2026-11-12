"""Capture on a router device: `tcpdump -w -` over a binary SSH exec stream into a .pcap file under
Documents\\OpenWrtGUI\\captures, or live into Wireshark. The app's own SSH is always filtered out, so a
capture on the device that carries it does not stream itself back. Allowed while Bench Guard is live (spec 6),
except on mon0, which first creates a monitor interface on the radio."""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from openwrtgui.capture.wireshark import find_wireshark, open_live
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.net.service import NetworkService
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import ByteStream, CommandResult, Transport, TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import shell_quote
from openwrtgui.wifi.monitor import MONITOR, MonitorLeases, RunFn

SCREEN = "Faults"
MAX_BYTES = 500 * 1024 * 1024
_FILTER = re.compile(r"[A-Za-z0-9 .:/()!&|<>=\[\]-]{0,200}")
FILTER_TEXT = "A filter uses letters, digits, spaces and . : / ( ) ! & | < > = [ ] -"


class Sink(Protocol):
    def write(self, data: bytes) -> Any: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class CaptureRequest:
    device: str
    filter: str = ""
    duration_s: int = 60
    output: Literal["file", "wireshark"] = "file"


@dataclass(frozen=True)
class CaptureView:
    id: str
    router_id: str
    device: str
    filter: str
    started_at: datetime
    duration_s: int
    output: Literal["file", "wireshark"]
    bytes: int
    running: bool
    path: str | None
    error: str | None


def capture_command(req: CaptureRequest, pc_ip: str | None, ssh_port: int, device: str | None = None) -> str:
    if not _FILTER.fullmatch(req.filter):
        raise ValueError(FILTER_TEXT)
    if not 1 <= req.duration_s <= 3600:
        raise ValueError("A capture runs 1 to 3600 s")
    if not pc_ip:
        # the app's own SSH stream would be captured and sent back over itself, growing without end
        raise ValueError(
            "Could not tell this PC's address, so the capture cannot leave out the app's own SSH."
        )
    expr = f"not (host {pc_ip} and tcp port {ssh_port})"
    if req.filter.strip():
        expr += f" and ({req.filter.strip()})"
    return f"timeout {req.duration_s} tcpdump -i {device or req.device} -U -s 0 -w - {shell_quote(expr)}"


def _size(n: int) -> str:
    return f"{n // 2**20} MB" if n >= 2**20 and n % 2**20 == 0 else f"{n} B"


class CaptureService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        net: NetworkService,
        documents: Path,
        wireshark: Callable[[], Path | None] = find_wireshark,
        clock: Callable[[], datetime] = datetime.now,
        max_bytes: int = MAX_BYTES,
        monitors: MonitorLeases | None = None,
    ) -> None:
        self._monitors = monitors or MonitorLeases()
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._net = net
        self._documents = documents
        self._wireshark = wireshark
        self._clock = clock
        self._max_bytes = max_bytes
        self._views: dict[str, CaptureView] = {}
        self._streams: dict[str, ByteStream] = {}
        self._running: dict[str, str] = {}  # router id -> capture id
        self._tasks: set[asyncio.Task[None]] = set()

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def devices(self, router_id: str) -> list[str]:
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        status = await ubus_call(t, "network.device", "status") or {}
        up = [name for name, d in status.items() if isinstance(d, dict) and d.get("up")]
        wireless = await ubus_call(t, "network.wireless", "status") or {}
        for radio in wireless.values():
            for iface in radio.get("interfaces", []) if isinstance(radio, dict) else []:
                if iface.get("ifname") and iface["ifname"] not in up:
                    up.append(str(iface["ifname"]))
        return [*sorted(up), "mon0"]

    def wireshark_available(self) -> bool:
        return self._wireshark() is not None

    def list(self, router_id: str) -> list[CaptureView]:
        return [v for v in self._views.values() if v.router_id == router_id]

    def list_all(self) -> builtins.list[CaptureView]:
        return list(self._views.values())

    def _run_fn(self, rec: RouterRecord, t: Transport) -> RunFn:
        async def run(command: str, require_guard: bool) -> CommandResult:
            return await run_audited(
                t,
                command,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                source="app",
                require_guard=require_guard,
            )

        return run

    async def _monitor(self, rec: RouterRecord, t: Transport, capture_id: str) -> None:
        state = self._guard.state()
        if state.live:
            run = state.reasons[0].text if state.reasons else "a harness run"
            raise ValueError(f"mon0 needs a monitor interface on the radio; not while {run} runs")
        wireless = await ubus_call(t, "network.wireless", "status") or {}
        radio = next((name for name, r in wireless.items() if isinstance(r, dict) and r.get("up")), None)
        if radio is None:
            raise ValueError(f"{rec.name} has no radio on air for mon0")
        phy = (await ubus_call(t, "iwinfo", "phyname", {"section": radio}) or {}).get("phyname", "phy0")
        async with self._pool.write_lock(rec.id):  # not in the middle of a Wi-Fi or firewall apply
            try:  # shared with the beacon check and frame analysis (v0.7 plan D11)
                await self._monitors.acquire(rec.id, f"capture {capture_id}", phy, t, self._run_fn(rec, t))
            except ValueError as exc:
                raise ValueError(f"Could not create mon0 on {rec.name}: {exc}") from None

    async def _monitor_gone(self, rec: RouterRecord, t: Transport, capture_id: str) -> None:
        """Let go of the monitor interface; the last holder removes it, allowed during a run, as it only
        undoes what the app made."""
        with contextlib.suppress(TransportError):
            async with self._pool.write_lock(rec.id):
                await self._monitors.release(rec.id, f"capture {capture_id}", self._run_fn(rec, t))

    async def start(self, router_id: str, req: CaptureRequest) -> CaptureView:
        rec = self._record(router_id)
        if router_id in self._running:
            raise ValueError(f"A capture is already running on {rec.name}")
        self._running[router_id] = ""  # taken before any await: one capture per router
        try:
            return await self._start(rec, req)
        except BaseException:
            self._running.pop(router_id, None)
            raise

    async def _start(self, rec: RouterRecord, req: CaptureRequest) -> CaptureView:
        # only a device the router lists: the name goes into the command and the file name
        if req.device not in await self.devices(rec.id):
            raise ValueError(f"{rec.name} has no network device {req.device!r}")
        net = await self._net.state(rec.id)
        mon0 = req.device == "mon0"
        device = MONITOR if mon0 else req.device
        command = capture_command(req, net.pc_ip, rec.port, device)
        exe = self._wireshark() if req.output == "wireshark" else None
        if req.output == "wireshark" and exe is None:
            raise ValueError("Wireshark is not installed on this PC")
        capture_id = secrets.token_hex(4)
        t = await self._pool.get(rec)
        if mon0:
            await self._monitor(rec, t, capture_id)
        sink: Sink | None = None
        path: Path | None = None
        try:  # nothing is left behind when the capture cannot start: no monitor interface, no file
            if exe is not None:
                sink = open_live(exe)
            else:
                folder = self._documents / "OpenWrtGUI" / "captures"
                folder.mkdir(parents=True, exist_ok=True)
                # the id too: a second capture in the same second must not overwrite the first
                path = folder / f"{rec.id}-{req.device}-{self._clock():%Y%m%d-%H%M%S}-{capture_id}.pcap"
                sink = path.open("xb")
            stream = await t.stream(command)  # type: ignore[attr-defined]
        except BaseException:
            if sink is not None:
                sink.close()
            if path is not None:
                path.unlink(missing_ok=True)
            if mon0:
                await self._monitor_gone(rec, t, capture_id)
            raise
        self._audit.record(
            router=rec.id,
            screen=SCREEN,
            command=f"capture {device} {shell_quote(req.filter)}",
            exit_status=None,
            source="user",
        )
        view = CaptureView(
            capture_id,
            rec.id,
            req.device,
            req.filter,
            self._clock(),
            req.duration_s,
            req.output,
            0,
            True,
            str(path) if path else None,
            None,
        )
        self._views[view.id] = view
        self._streams[view.id] = stream
        self._running[rec.id] = view.id
        task = asyncio.create_task(self._pump(rec, t, view.id, stream, sink, mon0))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return view

    async def _pump(
        self, rec: RouterRecord, t: Transport, capture_id: str, stream: ByteStream, sink: Sink, mon0: bool
    ) -> None:
        total = 0
        error: str | None = None
        try:
            while chunk := await stream.read(65536):
                sink.write(chunk)
                total += len(chunk)
                self._views[capture_id] = replace(self._views[capture_id], bytes=total)
                if total >= self._max_bytes:
                    error = f"Stopped at the size cap ({_size(self._max_bytes)})"
                    break
        except (TransportError, OSError) as exc:
            error = str(exc)
        finally:
            with contextlib.suppress(TransportError, OSError):
                await stream.close()
            sink.close()
            if error is None and stream.exit_status not in (0, 124, None) and not total:
                error = stream.stderr.strip() or f"tcpdump exited {stream.exit_status}"
            self._audit.record(
                router=rec.id,
                screen=SCREEN,
                command=f"capture stopped {total} B",
                exit_status=stream.exit_status,
                source="app",
            )
            if mon0:
                await self._monitor_gone(rec, t, capture_id)
            self._views[capture_id] = replace(
                self._views[capture_id], bytes=total, running=False, error=error
            )
            self._streams.pop(capture_id, None)
            if self._running.get(rec.id) == capture_id:
                del self._running[rec.id]

    async def stop(self, capture_id: str) -> CaptureView:
        view = self._views.get(capture_id)
        if view is None:
            raise ValueError(f"No capture {capture_id}")
        stream = self._streams.get(capture_id)
        if stream is not None:
            with contextlib.suppress(TransportError, OSError):
                await stream.close()
        for _ in range(50):  # let the pump finish
            if not self._views[capture_id].running:
                break
            await asyncio.sleep(0.01)
        return self._views[capture_id]
