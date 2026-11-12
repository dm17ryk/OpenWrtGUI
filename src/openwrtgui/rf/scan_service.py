"""Channel analysis (v0.7 plan D13): one passive scan on demand, with the survey of every channel around it.

A scan changes the radio, so it is a write: previewed, refused during a run or a step-through, run under the
router's write lock and audited. On an AP interface mac80211 needs `ap-force`; a parked radio gets a temporary
managed interface that is removed again, also when the scan fails.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.audit import AuditLog, Source
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.rf.air import (
    RADIO,
    SCAN_DEL,
    SCAN_IF,
    SCAN_INFO,
    SCAN_TIMEOUT_S,
    checked_ifname,
    scan_add,
    scan_command,
    survey_command,
)
from openwrtgui.rf.parse import parse_survey
from openwrtgui.rf.scan import Bss, ChannelLoad, channel_loads, parse_scan
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport, TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.parse import parse_iw_dev
from openwrtgui.wifi.service import PreviewChanged, WifiService
from openwrtgui.wifi.state import RadioState

SCREEN = "RF live"
Via = Literal["ap", "temporary"]


@dataclass(frozen=True)
class ScanPlan:
    router_id: str
    radio: str
    via: Via
    lines: tuple[str, ...]  # ap: the scan; temporary: add, scan, del
    warnings: tuple[str, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256("\n".join((self.via, *self.lines)).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ScanResult:
    router_id: str
    radio: str
    at: datetime
    via: Via
    seconds: float
    networks: tuple[Bss, ...]  # strongest first
    channels: tuple[ChannelLoad, ...]  # the radio's allowed channels, ascending


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _no_busy(_router_id: str) -> str | None:
    return None


class ScanService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        wifi: WifiService,
        busy: Callable[[str], str | None] = _no_busy,
        clock: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._wifi = wifi
        self.busy = busy  # the step-through's (plan D8), set once the step service exists
        self._clock = clock
        self._monotonic = monotonic
        self._last: dict[tuple[str, str], ScanResult] = {}

    async def _where(self, router_id: str, radio: str) -> tuple[RouterRecord, Transport, RadioState, str]:
        if not RADIO.fullmatch(radio):
            raise ValueError(f"{radio!r} is not a radio name")
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        state = await self._wifi.state(router_id)
        found = next((r for r in state.radios if r.name == radio), None)
        if found is None:
            raise ValueError(f"{radio} is not a radio of {rec.name}")
        t = await self._pool.get(rec)
        phy = (await ubus_call(t, "iwinfo", "phyname", {"section": radio}) or {}).get("phyname", "phy0")
        return rec, t, found, checked_ifname(str(phy))

    @staticmethod
    def _ap(radio: RadioState) -> str | None:
        if radio.up and radio.actual is not None and radio.actual.ifname:
            return checked_ifname(radio.actual.ifname)
        return None

    def _plan(self, rec: RouterRecord, radio: RadioState, phy: str) -> ScanPlan:
        ap = self._ap(radio)
        if ap is not None:
            names = ", ".join(s.ssid for s in radio.ssids) or radio.name
            warning = f"Stations on {names} may miss up to about 2 s of traffic during the scan."
            return ScanPlan(rec.id, radio.name, "ap", (scan_command(ap, on_ap=True),), (warning,))
        lines = (scan_add(phy), scan_command(SCAN_IF, on_ap=False), SCAN_DEL)
        return ScanPlan(rec.id, radio.name, "temporary", lines, ())

    async def preview(self, router_id: str, radio: str) -> ScanPlan:
        rec, _t, found, phy = await self._where(router_id, radio)
        return self._plan(rec, found, phy)

    def last(self, router_id: str, radio: str) -> ScanResult | None:
        return self._last.get((router_id, radio))

    async def _run(
        self,
        t: Transport,
        rec: RouterRecord,
        command: str,
        *,
        source: Source = "user",
        require_guard: bool = True,
        timeout: float = 15.0,
    ) -> CommandResult:
        return await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            source=source,
            require_guard=require_guard,
            timeout=timeout,
        )

    async def scan(self, router_id: str, radio: str, digest: str) -> ScanResult:
        self._guard.require_clear()
        rec, t, found, phy = await self._where(router_id, radio)
        if (why := self.busy(rec.id)) is not None:
            raise RouterBusy(why)
        plan = self._plan(rec, found, phy)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        own = {
            i.addr.lower() for i in parse_iw_dev((await t.run("iw dev")).stdout) if i.type == "AP" and i.addr
        }
        started = self._monotonic()
        iface = self._ap(found) or SCAN_IF
        async with self._pool.write_lock(rec.id):
            if plan.via == "temporary":
                added = await self._run(t, rec, plan.lines[0])
                if not added.ok:
                    await self._cleanup(t, rec)
                    raise ValueError(f"{rec.name} refused the scan interface: {_reason(added)}")
            try:
                before = parse_survey((await t.run(survey_command(iface))).stdout)
                done = await self._run(
                    t, rec, scan_command(iface, on_ap=plan.via == "ap"), timeout=SCAN_TIMEOUT_S
                )
                after = parse_survey((await t.run(survey_command(iface))).stdout)
            finally:
                if plan.via == "temporary":
                    await self._cleanup(t, rec)
        if not done.ok:
            raise ValueError(f"{rec.name} refused the scan: {_reason(done)}")
        networks = sorted(
            parse_scan(done.stdout, own),
            key=lambda b: b.signal_dbm if b.signal_dbm is not None else -999.0,
            reverse=True,
        )
        result = ScanResult(
            router_id=rec.id,
            radio=radio,
            at=self._clock(),
            via=plan.via,
            seconds=round(self._monotonic() - started, 1),
            networks=tuple(networks),
            channels=tuple(channel_loads(before, after, networks, found.limits.channels, found.band)),
        )
        self._last[(rec.id, radio)] = result
        return result

    async def _cleanup(self, t: Transport, rec: RouterRecord) -> None:
        """Remove the temporary interface: allowed during a run, it only undoes what the scan made. A refused
        removal is checked (already gone counts as removed) and tried once more; ValueError when the
        interface is still there, so a scan never reports success with it left on the radio."""
        why = ""
        for _ in range(2):
            try:
                done = await self._run(t, rec, SCAN_DEL, source="app", require_guard=False)
                if done.ok or not (await t.run(SCAN_INFO)).ok:
                    return
                why = _reason(done)
            except TransportError as exc:
                why = str(exc)
        raise ValueError(f"{SCAN_IF} is still on {rec.name}: {why}. Remove it with `{SCAN_DEL}`.")
