"""Wi-Fi changes: an exact preview, applied under the write lock, proven on air (plan: "Wi-Fi rules")."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.audit import AuditLog, mask
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.probe.status import RouterStatus, ssids_on_air
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport, TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import UciOp, drop_unchanged, render_uci
from openwrtgui.uci import after as after_ops
from openwrtgui.wifi.compile import (
    apply_script,
    compile_channels,
    compile_modes,
    compile_ssid,
    compile_txpower,
    mask_command,
    reload_command,
    tx_mask_args,
)
from openwrtgui.wifi.model import CCK_BASIC_KBPS, OFDM_BASIC_KBPS, ModeSelection, RadioRequest
from openwrtgui.wifi.monitor import MONITOR, MonitorLeases
from openwrtgui.wifi.options import OptionEdit, OptionRow, compile_edits, option_rows
from openwrtgui.wifi.parse import IwDevInfo, parse_beacon_rates, parse_iw_dev, parse_iw_dev_info
from openwrtgui.wifi.state import RadioState, WifiState, modes_from_uci, read_uci, read_wifi, ssid_sections
from openwrtgui.wifi.stations import Station, del_client_command, read_stations

SCREEN = "Wi-Fi"
_AUDIT_SCREEN: contextvars.ContextVar[str] = contextvars.ContextVar("wifi_audit_screen", default=SCREEN)
NOTHING = "Nothing to apply: the router already has these settings."
SCRIPT_TIMEOUT_S = 60.0
BLOCK_MIN_S, BLOCK_MAX_S = 10, 3600
CheckName = Literal["radio", "channel", "width", "TX power", "TX mask", "beacon rate"]
CHECKS: tuple[CheckName, ...] = ("radio", "channel", "width", "TX power", "TX mask", "beacon rate")


@dataclass(frozen=True)
class Expectation:
    radio_up: bool
    channels: frozenset[int] | None
    widths: frozenset[int]
    no_ht: bool
    txpower_dbm: int | None
    beacon_mbps: float | None


@dataclass(frozen=True)
class WifiPlan:
    router_id: str
    radio: str
    lines: tuple[str, ...]
    script: str = field(repr=False)
    mask_args: str | None
    warnings: tuple[str, ...]
    secrets: tuple[str, ...] = field(repr=False)
    expect: Expectation
    full_verify: bool = True
    reload: str = ""  # sent after `script` committed the change

    @property
    def digest(self) -> str:
        """Names the preview: Apply sends it back, so only the lines the user saw ever run."""
        return hashlib.sha256("\n".join(self.lines).encode()).hexdigest()[:16]

    @property
    def change_lines(self) -> tuple[str, ...]:
        """The lines without the TX-mask line, whose interface is known once the radio is up (v0.7 D3)."""
        return tuple(
            line for line in self.lines if not (line.startswith("iw dev ") and " set bitrates" in line)
        )


class RadioBusy(RouterBusy):
    """A step-through holds the radio (v0.7 plan D8): no other change to it until it ends (409)."""

    def __init__(self, what: str, router_name: str, radio: str) -> None:
        super().__init__(f"{what} runs on {router_name} {radio}: wait for it to end, or stop it")


class PreviewChanged(Exception):
    """The router changed between the preview and Apply: the lines to send are no longer the shown ones."""

    def __init__(self, router_name: str) -> None:
        super().__init__(f"{router_name} changed since the preview. Check the new preview, then apply.")


@dataclass(frozen=True)
class Check:
    name: CheckName
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class ApplyResult:
    router_id: str
    radio: str
    applied: bool
    verified: bool
    checks: tuple[Check, ...]
    error: str | None


def _mask_after(
    uci: Mapping[str, str], ops: Sequence[UciOp], radio: RadioState, modes: ModeSelection | None = None
) -> str | None:
    """The TX mask that goes with the radio's modes after `ops`: every reload the app makes drops the
    runtime mask, so it is set again. None for modes set outside the selector (custom)."""
    chosen = modes or modes_from_uci(after_ops(uci, ops), radio.name, radio.limits.max_htmode)
    return None if chosen.kind == "custom" else tx_mask_args(chosen, radio.limits.mcs)


def _as_previewed(rec: RouterRecord, plan: WifiPlan, digest: str | None) -> WifiPlan:
    if digest is not None and digest != plan.digest:
        raise PreviewChanged(rec.name)
    return plan


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _beacon_mbps(after: Mapping[str, str], radio: str) -> float:
    basic = after.get(f"wireless.{radio}.basic_rate")
    if basic:
        return min(int(r) for r in basic.split()) / 1000
    has_b = after.get(f"wireless.{radio}.legacy_rates") == "1"
    return (CCK_BASIC_KBPS if has_b else OFDM_BASIC_KBPS)[0] / 1000


def _expectation(after: Mapping[str, str], radio: RadioState, chosen: frozenset[int] | None) -> Expectation:
    p = f"wireless.{radio.name}."
    htmode = after.get(p + "htmode", radio.limits.max_htmode)
    if htmode == "HT40":
        widths = frozenset({40}) if after.get(p + "noscan") == "1" else frozenset({20, 40})
    else:
        widths = frozenset({20})
    txpower = after.get(p + "txpower")
    return Expectation(
        radio_up=after.get(p + "disabled") != "1",
        channels=chosen,
        widths=widths,
        no_ht=htmode == "NOHT",
        txpower_dbm=int(txpower) if txpower and txpower.isdigit() else None,
        beacon_mbps=_beacon_mbps(after, radio.name),
    )


def _chosen_channels(after: Mapping[str, str], radio: str) -> frozenset[int] | None:
    channel = after.get(f"wireless.{radio}.channel", "auto")
    if channel.isdigit():
        return frozenset({int(channel)})
    listed = after.get(f"wireless.{radio}.channels", "")
    if listed and "-" not in listed:
        return frozenset(int(c) for c in listed.split() if c.isdigit())
    return None


class WifiService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        descriptions: MutableMapping[str, SelfDescription],
        statuses: Mapping[str, RouterStatus],
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        settle_timeout_s: float = 30.0,
        poll_s: float = 1.0,
        monitors: MonitorLeases | None = None,
    ) -> None:
        self._monitors = monitors or MonitorLeases()
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._descriptions = descriptions
        self._statuses = statuses
        self._clock = clock
        self._sleep = sleep
        self._settle_timeout_s = settle_timeout_s
        self._poll_s = poll_s
        self._mask_marks: dict[tuple[str, str], int] = {}
        self._held: dict[tuple[str, str], tuple[object, str]] = {}  # (router, radio) -> (token, what)

    # ---------------------------------------------------------------- the radio hold (v0.7 plan D8)
    def _name(self, router_id: str) -> str:
        rec = self._routers.get(router_id)
        return rec.name if rec else router_id

    def hold_radio(self, router_id: str, radio: str, what: str) -> object:
        """No other change to this radio until release_radio(token); RadioBusy when someone holds it."""
        held = self._held.get((router_id, radio))
        if held is not None:
            raise RadioBusy(held[1], self._name(router_id), radio)
        token = object()
        self._held[(router_id, radio)] = (token, what)
        return token

    def release_radio(self, token: object) -> None:
        self._held = {k: v for k, v in self._held.items() if v[0] is not token}

    def radio_holder(self, router_id: str, radio: str) -> str | None:
        held = self._held.get((router_id, radio))
        return held[1] if held else None

    def _check_hold(self, router_id: str, radio: str, holder: object | None) -> None:
        held = self._held.get((router_id, radio))
        if held is not None and held[0] is not holder:
            raise RadioBusy(held[1], self._name(router_id), radio)

    @property
    def monitors(self) -> MonitorLeases:
        """The shared owgmon0 of every router (v0.7 plan D11): capture and frame analysis hold it too."""
        return self._monitors

    # ---------------------------------------------------------------- reading
    async def _connect(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec, await self._pool.get(rec)

    async def _description(self, rec: RouterRecord, t: Transport) -> SelfDescription:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        return desc

    async def _read(self, router_id: str) -> tuple[RouterRecord, Transport, WifiState, dict[str, str]]:
        rec, t = await self._connect(router_id)
        uci = await read_uci(t)
        state = await read_wifi(
            t, rec.id, await self._description(rec, t), self._mask_marks, self._clock, uci
        )
        return rec, t, state, uci

    async def state(self, router_id: str) -> WifiState:
        return (await self._read(router_id))[2]

    # ---------------------------------------------------------------- all options
    async def options(self, router_id: str, radio: str) -> list[OptionRow]:
        rec, t = await self._connect(router_id)
        uci = await read_uci(t)
        validate = (await self._description(rec, t)).wireless_options.get(radio)
        if validate is None:
            raise ValueError(f"{radio} is not a radio of {rec.name}")
        return option_rows(radio, validate, uci, ssid_sections(uci, radio))

    async def plan_options(self, router_id: str, radio: str, edits: Sequence[OptionEdit]) -> WifiPlan:
        ops, secrets = compile_edits(edits, await self.options(router_id, radio))
        return await self.plan_ops(router_id, radio, ops, secrets)

    async def apply_options(
        self, router_id: str, radio: str, edits: Sequence[OptionEdit], digest: str | None = None
    ) -> ApplyResult:
        self._check_hold(router_id, radio, None)
        ops, secrets = compile_edits(edits, await self.options(router_id, radio))
        return await self.apply_ops(router_id, radio, ops, secrets, digest=digest)

    # ---------------------------------------------------------------- stations
    async def stations(self, router_id: str) -> list[Station]:
        _rec, t = await self._connect(router_id)
        status = await ubus_call(t, "network.wireless", "status") or {}
        ifaces = [
            (str(i["ifname"]), str(i.get("config", {}).get("ssid", "")))
            for radio in status.values()
            if radio.get("up")
            for i in radio.get("interfaces", [])
            if i.get("ifname")
        ]
        return await read_stations(t, ifaces)

    async def _station_action(self, router_id: str, mac: str, ban_ms: int) -> CommandResult:
        rec, t = await self._connect(router_id)
        station = next((s for s in await self.stations(router_id) if s.mac == mac.lower()), None)
        if station is None:
            raise ValueError(f"{mac.lower()} is not connected to {rec.name}")
        async with self._pool.write_lock(rec.id):
            result: CommandResult = await self._run(
                t, rec, del_client_command(station.ifname, station.mac, ban_ms)
            )
        return result

    async def deauth(self, router_id: str, mac: str) -> CommandResult:
        return await self._station_action(router_id, mac, 0)

    async def block(self, router_id: str, mac: str, seconds: int) -> CommandResult:
        if not BLOCK_MIN_S <= seconds <= BLOCK_MAX_S:
            raise ValueError(f"Block for {BLOCK_MIN_S} to {BLOCK_MAX_S} seconds")
        return await self._station_action(router_id, mac, seconds * 1000)

    # ---------------------------------------------------------------- planning
    def _radio(self, state: WifiState, rec: RouterRecord, name: str) -> RadioState:
        radio = next((r for r in state.radios if r.name == name), None)
        if radio is None:
            raise ValueError(f"{name} is not a radio of {rec.name}")
        return radio

    def _warnings(
        self, rec: RouterRecord, radio: RadioState, after: Mapping[str, str], up: bool
    ) -> tuple[str, ...]:
        if radio.up or not up:
            return ()
        names = [after.get(f"wireless.{s.section}.ssid", s.ssid) for s in radio.ssids]
        out = []
        for other_id, status in self._statuses.items():
            other = self._routers.get(other_id)
            if other_id == rec.id or other is None:
                continue
            on_air = ssids_on_air(status)
            out += [
                f"{name} is already on air on {other.name}. The bench rule is one radio on air per SSID."
                for name in names
                if name in on_air
            ]
        return tuple(out)

    def _plan(
        self,
        rec: RouterRecord,
        radio: RadioState,
        uci: Mapping[str, str],
        ops: Sequence[UciOp],
        secrets: Sequence[str],
        mask_args: str | None,
        full_verify: bool,
        allow_empty: bool = False,
    ) -> WifiPlan:
        ops = drop_unchanged(ops, uci)
        after = after_ops(uci, ops)
        expect = _expectation(after, radio, _chosen_channels(after, radio.name))
        if not expect.radio_up:
            mask_args = None
        if not ops and not (mask_args is not None and radio.mask == "missing") and not allow_empty:
            raise ValueError(NOTHING)
        script = apply_script(radio.name, ops) if ops else ""
        reload = reload_command(radio.name) if ops else ""
        lines = [mask(line, secrets) for line in script.splitlines()]
        if reload:
            lines.append(reload)
        if mask_args is not None:
            ifname = radio.actual.ifname if radio.up and radio.actual else f"<AP interface of {radio.name}>"
            lines.append(mask_command(ifname, mask_args))
        return WifiPlan(
            router_id=rec.id,
            radio=radio.name,
            lines=tuple(lines),
            script=script,
            mask_args=mask_args,
            warnings=self._warnings(rec, radio, after, expect.radio_up),
            secrets=tuple(secrets),
            expect=expect,
            full_verify=full_verify,
            reload=reload,
        )

    async def plan(self, router_id: str, req: RadioRequest) -> WifiPlan:
        rec, _t, state, uci = await self._read(router_id)
        return self._plan_request(rec, state, uci, req)

    def _request_ops(
        self, rec: RouterRecord, state: WifiState, uci: Mapping[str, str], req: RadioRequest
    ) -> tuple[RadioState, list[UciOp], list[str]]:
        radio = self._radio(state, rec, req.radio)
        limits = radio.limits
        ops: list[UciOp] = []
        if req.modes is not None:
            ops += compile_modes(radio.name, req.modes, limits)
        if req.channels is not None:
            ops += compile_channels(radio.name, req.channels, limits)
        if req.txpower is not None:
            ops += compile_txpower(radio.name, req.txpower, limits)
        own = {s.section for s in radio.ssids}
        for s in req.ssids:
            if s.section not in own:  # never a section name from outside into the shell
                raise ValueError(f"{s.section} is not an SSID of {radio.name}")
            ops += compile_ssid(s, radio.band, limits.sae, uci)
        return radio, ops, [s.key for s in req.ssids if s.key]

    def _plan_request(
        self, rec: RouterRecord, state: WifiState, uci: Mapping[str, str], req: RadioRequest
    ) -> WifiPlan:
        radio, ops, secrets = self._request_ops(rec, state, uci, req)
        mask_args = _mask_after(uci, ops, radio, req.modes)
        return self._plan(rec, radio, uci, ops, secrets, mask_args, full_verify=True)

    async def plan_sequence(
        self, router_id: str, radio_name: str, requests: Sequence[RadioRequest], tail_ops: Sequence[UciOp]
    ) -> tuple[list[WifiPlan], WifiPlan]:
        """A step-through's preview (v0.7 plan D3): one read, then each request planned on the config the
        one before leaves, and the restore (`tail_ops`) last. A step that changes nothing keeps its place."""
        rec, _t, state, uci = await self._read(router_id)
        current: dict[str, str] = dict(uci)
        plans: list[WifiPlan] = []
        for req in requests:
            if req.radio != radio_name:
                raise ValueError(f"Every step is on {radio_name}")
            radio, ops, secrets = self._request_ops(rec, state, current, req)
            mask_args = _mask_after(current, ops, radio, req.modes)
            plans.append(self._plan(rec, radio, current, ops, secrets, mask_args, True, allow_empty=True))
            current = after_ops(current, drop_unchanged(ops, current))
        radio = self._radio(state, rec, radio_name)
        mask_args = _mask_after(current, tail_ops, radio)
        restore = self._plan(rec, radio, current, tail_ops, (), mask_args, False, allow_empty=True)
        return plans, restore

    async def plan_ops(
        self, router_id: str, radio_name: str, ops: Sequence[UciOp], secrets: Sequence[str] = ()
    ) -> WifiPlan:
        rec, _t, state, uci = await self._read(router_id)
        radio = self._radio(state, rec, radio_name)
        return self._plan(rec, radio, uci, ops, secrets, _mask_after(uci, ops, radio), full_verify=False)

    # ---------------------------------------------------------------- applying
    async def apply(
        self, router_id: str, req: RadioRequest, digest: str | None = None, *, holder: object | None = None
    ) -> ApplyResult:
        self._check_hold(router_id, req.radio, holder)
        rec, t, state, uci = await self._read(router_id)
        plan = self._plan_request(rec, state, uci, req)
        return await self._execute(rec, t, _as_previewed(rec, plan, digest))

    async def apply_ops(
        self,
        router_id: str,
        radio_name: str,
        ops: Sequence[UciOp],
        secrets: Sequence[str] = (),
        *,
        digest: str | None = None,
        screen: str = SCREEN,
        hold_lock: bool = True,
        holder: object | None = None,
    ) -> ApplyResult:
        """`screen` names the screen in the audit log: Network & DHCP applies its saved MAC lists here.
        `hold_lock=False`: the caller holds the router's write lock already. `holder`: the step-through's
        token while it holds the radio (v0.7 plan D8)."""
        self._check_hold(router_id, radio_name, holder)
        token = _AUDIT_SCREEN.set(screen)
        try:
            rec, t, state, uci = await self._read(router_id)
            radio = self._radio(state, rec, radio_name)
            plan = self._plan(rec, radio, uci, ops, secrets, _mask_after(uci, ops, radio), full_verify=False)
            return await self._execute(rec, t, _as_previewed(rec, plan, digest), hold_lock=hold_lock)
        finally:
            _AUDIT_SCREEN.reset(token)

    async def _run(self, t: Transport, rec: RouterRecord, command: str, **kw: Any) -> Any:
        return await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=_AUDIT_SCREEN.get(),
            guard=self._guard,
            audit=self._audit,
            **kw,
        )

    async def _execute(
        self, rec: RouterRecord, t: Transport, plan: WifiPlan, *, hold_lock: bool = True
    ) -> ApplyResult:
        checks: list[Check] = []
        applied = False
        reload_error: str | None = None
        lock = self._pool.write_lock(rec.id) if hold_lock else contextlib.nullcontext()
        async with lock:
            try:
                if plan.script:
                    try:
                        done = await self._run(
                            t, rec, plan.script, secrets=plan.secrets, timeout=SCRIPT_TIMEOUT_S
                        )
                    except TransportError as exc:  # the commit may or may not have run
                        return self._finish(
                            rec,
                            plan,
                            [],
                            f"Lost the connection to {rec.name} while the change ran; "
                            f"it may have been committed: {exc}",
                        )
                    if not done.ok:
                        reason = _reason(done)
                        return ApplyResult(
                            rec.id, plan.radio, False, False, (), f"The router refused the change: {reason}"
                        )
                    applied = True
                    reloaded = await self._run(t, rec, plan.reload, timeout=SCRIPT_TIMEOUT_S)
                    if not reloaded.ok:
                        reload_error = (
                            f"The radio reload failed after the change was committed: {_reason(reloaded)}"
                        )
                checks = await self._verify(rec, t, plan)
            except GuardLocked as exc:
                if not applied:
                    raise
                reasons = exc.state.reasons
                why = reasons[0].text if reasons else "Bench Guard: read-only"
                return self._finish(
                    rec, plan, checks, f"Bench Guard went live after the change was committed: {why}"
                )
            except TransportError as exc:
                if not applied:
                    raise
                return self._finish(
                    rec,
                    plan,
                    checks,
                    f"Lost the connection to {rec.name} after the change was committed: {exc}",
                )
        return self._finish(rec, plan, checks, reload_error)

    def _finish(
        self, rec: RouterRecord, plan: WifiPlan, checks: list[Check], error: str | None
    ) -> ApplyResult:
        failed = [c.name for c in checks if c.ok is False]
        verified = error is None and not failed and any(c.ok for c in checks)
        self._audit.record(
            router=rec.id,
            screen=_AUDIT_SCREEN.get(),
            command=f"verify {plan.radio}",
            exit_status=None,
            verify="pass" if verified else f"fail: {error or ', '.join(failed) or 'not verified'}",
            source="app",
        )
        return ApplyResult(
            rec.id, plan.radio, plan.script != "" or error is None, verified, tuple(checks), error
        )

    async def _settle(self, t: Transport, radio: str, up: bool) -> dict[str, Any] | None:
        waited = 0.0
        while True:
            status = (await ubus_call(t, "network.wireless", "status") or {}).get(radio, {})
            if not status.get("pending") and bool(status.get("up")) == up:
                return dict(status)
            if waited >= self._settle_timeout_s:
                return None
            await self._sleep(self._poll_s)
            waited += self._poll_s

    async def _operating(self, t: Transport, ifname: str) -> IwDevInfo:
        """`iw dev X info` once the AP interface operates. netifd reports the radio up while hostapd may still
        be in COUNTRY_UPDATE (AP2, 2026-11-09): no channel yet, and `set bitrates` fails."""
        waited = 0.0
        while True:
            info = parse_iw_dev_info((await t.run(f"iw dev {ifname} info")).stdout)
            if info.channel is not None or waited >= self._settle_timeout_s:
                return info
            await self._sleep(self._poll_s)
            waited += self._poll_s

    async def _verify(self, rec: RouterRecord, t: Transport, plan: WifiPlan) -> list[Check]:
        expect = plan.expect
        settled: dict[str, Any] | None = (
            await self._settle(t, plan.radio, expect.radio_up) if plan.script else {"up": True}
        )
        if settled is None:
            return [Check("radio", False, f"did not settle within {self._settle_timeout_s:.0f} s")]
        phy = str(
            (await ubus_call(t, "iwinfo", "phyname", {"section": plan.radio}) or {}).get("phyname", "phy0")
        )
        if not expect.radio_up:
            on_phy = [
                i
                for i in parse_iw_dev((await t.run("iw dev")).stdout)
                if f"phy{i.phy}" == phy and i.type == "AP"
            ]
            radio_ok = Check(
                "radio",
                not on_phy,
                "parked: no AP interface" if not on_phy else "an AP interface is still up",
            )
            return [radio_ok, *[Check(n, None, "not run: radio parked") for n in CHECKS[1:]]]
        ifname = next((i["ifname"] for i in settled.get("interfaces", []) if i.get("ifname")), None)
        if ifname is None:
            status = (await ubus_call(t, "network.wireless", "status") or {}).get(plan.radio, {})
            ifname = next((i["ifname"] for i in status.get("interfaces", []) if i.get("ifname")), None)
        if ifname is None:
            return [Check("radio", False, "no AP interface came up")]
        checks = [Check("radio", True, f"up on {ifname}")]
        info = await self._operating(t, ifname)
        mask_check = Check("TX mask", None, "not changed")
        if plan.mask_args is not None:
            done = await self._run(t, rec, mask_command(ifname, plan.mask_args), source="app")
            mask_check = Check("TX mask", done.ok, "cleared" if not plan.mask_args else plan.mask_args)
        if plan.mask_args and mask_check.ok and info.ifindex is not None:
            self._mask_marks[(rec.id, ifname)] = info.ifindex
        elif plan.mask_args == "":
            self._mask_marks.pop((rec.id, ifname), None)
        checks.append(self._channel_check(info, expect))
        width_ok = info.width_mhz in expect.widths and info.no_ht == expect.no_ht
        width_text = (
            f"{info.width_mhz} MHz{' (no HT)' if info.no_ht else ''}" if info.width_mhz else "not reported"
        )
        checks.append(Check("width", width_ok, width_text))
        checks.append(self._power_check(info, expect))
        if not plan.full_verify:
            return checks
        checks.append(mask_check)
        checks.append(await self._beacon_check(rec, t, phy, info, expect))
        return checks

    @staticmethod
    def _channel_check(info: Any, expect: Expectation) -> Check:
        if info.channel is None:
            return Check("channel", False, "not reported")
        ok = expect.channels is None or info.channel in expect.channels
        return Check("channel", ok, f"channel {info.channel}")

    @staticmethod
    def _power_check(info: Any, expect: Expectation) -> Check:
        actual = info.txpower_dbm
        if actual is None:
            return Check("TX power", False, "not reported")
        if expect.txpower_dbm is None:
            return Check("TX power", True, f"auto, actual {actual:.2f} dBm")
        ok = abs(actual - expect.txpower_dbm) <= 1
        return Check("TX power", ok, f"set {expect.txpower_dbm} dBm, actual {actual:.2f} dBm")

    async def _beacon_check(
        self, rec: RouterRecord, t: Transport, phy: str, info: Any, expect: Expectation
    ) -> Check:
        if info.addr is None or expect.beacon_mbps is None:
            return Check("beacon rate", False, "no BSSID to listen for")
        capture = (
            f"timeout 5 tcpdump -i {MONITOR} -e -n -c 5 -l "
            f"'type mgt subtype beacon and wlan addr2 {info.addr}'"
        )

        async def run(command: str, require_guard: bool) -> CommandResult:
            # cleaning up restores the radio, so the removal runs even when a run has started meanwhile;
            # `iw`, not `ip link del`: AP2's kernel refuses the latter for a wireless interface
            done: CommandResult = await self._run(t, rec, command, source="app", require_guard=require_guard)
            return done

        holder = f"beacon check {rec.id} {phy}"
        try:  # a capture or frame analysis may hold owgmon0 already: it is shared, never removed under them
            await self._monitors.acquire(rec.id, holder, phy, t, run)
        except ValueError as exc:
            return Check("beacon rate", False, f"no monitor interface: {exc}")
        try:
            heard = (await self._run(t, rec, capture, source="app", timeout=15.0)).stdout
        finally:
            removed = await self._monitors.release(rec.id, holder, run)
        if removed is not None and not removed.ok:
            return Check("beacon rate", False, f"{MONITOR} is still on the radio: {removed.stderr.strip()}")
        rates = parse_beacon_rates(heard)
        if not rates:
            return Check("beacon rate", False, "no beacon seen in 5 s")
        if set(rates) != {expect.beacon_mbps}:
            seen = ", ".join(f"{r:.1f}" for r in sorted(set(rates)))
            return Check("beacon rate", False, f"beacons at {seen} Mb/s, expected {expect.beacon_mbps:.1f}")
        return Check("beacon rate", True, f"{expect.beacon_mbps:.1f} Mb/s ×{len(rates)}")


__all__ = [
    "CHECKS",
    "ApplyResult",
    "Check",
    "Expectation",
    "PreviewChanged",
    "WifiPlan",
    "WifiService",
    "render_uci",
]
