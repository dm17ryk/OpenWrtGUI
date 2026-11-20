"""Station management's reads and requests (v1.2b R8-R10), for ToolsService."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.tools.sessions import SCREEN, ToolPlan, tool_plan
from openwrtgui.tools.stations import (
    HOSTAPD_LIST,
    LISTEN_S,
    NO_ANSWER,
    RUNTIME,
    ActionResult,
    ApStations,
    BeaconRow,
    HostapdEvent,
    NeighbourEntry,
    StationAction,
    StationRow,
    StationsView,
    beacon_request_command,
    checked_mac,
    gone,
    hostapd_methods,
    listen_command,
    neighbour_entry,
    neighbours_set_command,
    no_method,
    not_supported,
    parse_event,
    transition_command,
)
from openwrtgui.transport.base import ByteStream, CommandResult, Transport, TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged, WifiService

METHOD_OF = {"transition": "bss_transition_request", "beacon": "rrm_beacon_req", "neighbours": "rrm_nr_set"}
LISTEN_NOTE = "  # 10 s, for the station's answer"


@dataclass(frozen=True)
class _Ap:
    ifname: str
    ssid: str
    channel: int | None


def _channel(value: Any) -> int | None:
    return int(value) if str(value).isdigit() else None


async def _aps(t: Transport) -> list[_Ap]:
    """The APs on air: each up radio's interfaces, with the channel it is on (iwinfo, else its config)."""
    status = await ubus_call(t, "network.wireless", "status") or {}
    out: list[_Ap] = []
    for radio in status.values():
        if not isinstance(radio, dict) or not radio.get("up"):
            continue
        for iface in radio.get("interfaces", []):
            if not iface.get("ifname"):
                continue
            ifname = str(iface["ifname"])
            info = await ubus_call(t, "iwinfo", "info", {"device": ifname}) or {}
            channel = _channel(info.get("channel")) or _channel(radio.get("config", {}).get("channel"))
            out.append(_Ap(ifname, str(iface.get("config", {}).get("ssid", "")), channel))
    return out


async def _own(t: Transport, ifname: str, source: str) -> NeighbourEntry | None:
    own = await ubus_call(t, f"hostapd.{ifname}", "rrm_nr_get_own") or {}
    return neighbour_entry(own.get("value"), source)


def _detail(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


class StationTools:
    def __init__(
        self,
        *,
        routers: RouterStore,
        pool: ConnectionPool,
        guard: BenchGuard,
        audit: AuditLog,
        wifi: WifiService,
        listen_s: float = LISTEN_S,
    ) -> None:
        self._routers = routers
        self._pool = pool
        self._guard = guard
        self._audit = audit
        self._wifi = wifi
        self._listen_s = listen_s

    # ---------------------------------------------------------------- reads
    async def _candidates(
        self, rec: RouterRecord, own: Sequence[NeighbourEntry], notes: list[str]
    ) -> list[NeighbourEntry]:
        """This router's APs, then each other router's APs on air (R8): their own neighbour reports."""
        out = list(own)
        for other in self._routers.list():
            # only routers the app reaches now: an unreachable one would add a connect wait to every view,
            # preview and apply (final review I4)
            if other.id == rec.id or not self._pool.health(other.id).online:
                continue
            try:
                t = await self._pool.get(other)
                for ap in await _aps(t):
                    entry = await _own(t, ap.ifname, f"{other.name} · {ap.ssid}")
                    if entry is not None:
                        out.append(entry)
            except (TransportError, ValueError) as exc:
                notes.append(f"Could not read {other.name}: {exc}")
        return out

    async def view(self, router_id: str) -> StationsView:
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        notes: list[str] = []
        methods = hostapd_methods((await t.run(HOSTAPD_LIST)).stdout)
        stations = await self._wifi.stations(router_id)
        aps: list[ApStations] = []
        for ap in await _aps(t):
            have = methods.get(ap.ifname, [])
            source = f"{rec.name} · {ap.ssid}"
            own = await _own(t, ap.ifname, source) if "rrm_nr_get_own" in have else None
            neighbours: list[NeighbourEntry] = []
            if "rrm_nr_list" in have:
                listed = await ubus_call(t, f"hostapd.{ap.ifname}", "rrm_nr_list") or {}
                for value in listed.get("list", []):
                    entry = neighbour_entry(value, source)
                    if entry is None:
                        notes.append(f"Left out an entry of {ap.ifname}'s neighbour list: {value!r}")
                    else:
                        neighbours.append(entry)
            rows = [
                StationRow(mac=s.mac, name=s.name, ip=s.ip, signal_dbm=s.signal_dbm)
                for s in stations
                if s.ifname == ap.ifname
            ]
            aps.append(
                ApStations(
                    ifname=ap.ifname,
                    ssid=ap.ssid,
                    channel=ap.channel,
                    methods=have,
                    own=own,
                    neighbours=neighbours,
                    stations=rows,
                )
            )
        candidates = await self._candidates(rec, [a.own for a in aps if a.own is not None], notes)
        return StationsView(aps=aps, candidates=candidates, notes=notes)

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    # ---------------------------------------------------------------- the plan
    async def plan(self, router_id: str, action: StationAction) -> tuple[ToolPlan, ApStations]:
        rec = self._record(router_id)
        view = await self.view(router_id)
        ap = next((a for a in view.aps if a.ifname == action.ifname), None)
        if ap is None:
            raise ValueError(f"{rec.name} has no SSID on air on {action.ifname}")
        method = METHOD_OF[action.kind]
        if method not in ap.methods:
            raise ValueError(no_method(method))
        by_bssid = {c.bssid: c for c in view.candidates}
        if action.kind == "neighbours":
            unknown = [b for b in action.neighbours if b.lower() not in by_bssid]
            if unknown:
                raise ValueError(f"{unknown[0]} is not one of the candidates")
            if ap.own is not None and ap.own.bssid in {b.lower() for b in action.neighbours}:
                # AP2 window: hostapd keeps the AP's own report out of its neighbour list
                raise ValueError(
                    f"{ap.own.bssid} is this SSID's own BSSID: hostapd keeps its own report apart, "
                    "not in its neighbour list."
                )
            entries = [by_bssid[b.lower()] for b in action.neighbours]
            command = neighbours_set_command(ap.ifname, [[e.bssid, e.ssid, e.nr] for e in entries])
            return tool_plan([command], [RUNTIME]), ap
        mac = checked_mac(action.mac or "")
        if mac not in {s.mac for s in ap.stations}:
            raise ValueError(gone(mac, ap.ssid))
        if action.kind == "transition":
            target = by_bssid.get((action.target or "").lower())
            if target is None:
                raise ValueError(f"{action.target} is not one of the candidates")
            command = transition_command(ap.ifname, mac, target.nr)
        else:
            if ap.channel is None:
                raise ValueError(f"Could not tell the channel {ap.ifname} is on")
            command = beacon_request_command(ap.ifname, mac, ap.channel)
        return tool_plan([command, listen_command(ap.ifname) + LISTEN_NOTE], []), ap

    # ---------------------------------------------------------------- the request
    async def apply(self, router_id: str, action: StationAction, digest: str) -> ActionResult:
        rec = self._record(router_id)
        self._guard.require_clear()
        plan, ap = await self.plan(router_id, action)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        listens = action.kind != "neighbours"
        own: Transport | None = None
        stream: ByteStream | None = None
        try:
            if listens:  # first, so the station's answer is not missed (R8)
                own = await self._pool.fresh(rec)
                stream = await own.stream(listen_command(ap.ifname))  # type: ignore[attr-defined]
                self._audit.record(
                    router=rec.id,
                    screen=SCREEN,
                    command=listen_command(ap.ifname),
                    exit_status=None,
                    source="app",
                )
            async with self._pool.write_lock(rec.id):
                t = await self._pool.get(rec)
                result = await run_audited(
                    t, plan.lines[0], router_id=rec.id, screen=SCREEN, guard=self._guard, audit=self._audit
                )
            if not result.ok:
                return self._refused(rec, action, ap, result)
            if stream is None:
                return ActionResult(ok=True, detail=RUNTIME, events=[], beacons=[], status_code=None)
            events = await self._events(stream, checked_mac(action.mac or ""))
        finally:
            if stream is not None:
                with contextlib.suppress(TransportError, OSError):
                    await stream.close()
            if own is not None:
                with contextlib.suppress(TransportError, OSError):
                    await own.close()
        return self._answered(action, events)

    def _refused(
        self, rec: RouterRecord, action: StationAction, ap: ApStations, result: CommandResult
    ) -> ActionResult:
        detail = _detail(result)
        if "Not supported" in detail:
            text = not_supported(rec.name, action.kind)
        elif "Not found" in detail and action.mac:
            text = gone(checked_mac(action.mac), ap.ssid)
        else:
            text = f"hostapd answered: {detail}"
        return ActionResult(ok=False, detail=text, events=[], beacons=[], status_code=None)

    def _answered(self, action: StationAction, events: list[HostapdEvent]) -> ActionResult:
        if not events:
            return ActionResult(ok=True, detail=NO_ANSWER, events=[], beacons=[], status_code=None)
        if action.kind == "transition":
            code = next(
                (
                    e.fields.get("status-code")
                    for e in events
                    if "bss-transition" in e.type and isinstance(e.fields.get("status-code"), int)
                ),
                None,
            )
            status = code if isinstance(code, int) and not isinstance(code, bool) else None
            detail = (
                f"The station answered the BSS transition request (status {status})."
                if status is not None
                else "The station sent a notification, but no BSS transition status."
            )
            return ActionResult(ok=True, detail=detail, events=events, beacons=[], status_code=status)
        beacons = [BeaconRow.of(e) for e in events if e.type == "beacon-report"]
        detail = f"The station sent {len(beacons)} beacon report{'s' if len(beacons) != 1 else ''}."
        return ActionResult(ok=True, detail=detail, events=events, beacons=beacons, status_code=None)

    async def _events(self, stream: ByteStream, mac: str) -> list[HostapdEvent]:
        """The station's notifications for up to listen_s; any other station's are left out."""
        events: list[HostapdEvent] = []
        loop = asyncio.get_running_loop()
        end = loop.time() + self._listen_s
        buf = b""

        def take(raw: bytes) -> None:
            event = parse_event(raw.decode(errors="replace"))
            if event is not None and str(event.fields.get("address", "")).lower() == mac:
                events.append(event)

        while (left := end - loop.time()) > 0:
            try:
                chunk = await asyncio.wait_for(stream.read(65536), left)
            except (TimeoutError, TransportError, OSError):
                break
            if not chunk:
                break
            *lines, buf = (buf + chunk).split(b"\n")
            for raw in lines:
                take(raw)
        if buf.strip():
            take(buf)
        return events
