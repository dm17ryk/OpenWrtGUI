"""Step-through steps (v0.7 plan D2-D6): which steps, in which order, and what a step-through saves and reads.

Every ticked mode × ticked channel × (optional) ticked TX power, one pure mode per step, in the order mode
(b, g, n20, n40) → channel ascending → power ascending. Each step is the Wi-Fi Apply of exactly that.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from openwrtgui.uci import UciOp
from openwrtgui.wifi.model import (
    MODES,
    NO_CHANNEL,
    NO_MODE,
    ChannelSelection,
    Mode,
    ModeSelection,
    RadioLimits,
    RadioRequest,
    TxPowerSetting,
)

Advance = Literal["timer", "manual", "rejoin"]
MAX_STEPS = 200
DWELL_S = (10, 3600)
REJOIN_LIMIT_S = (30, 600)
STEP_OVERHEAD_S = 20  # the estimate per step: apply, reload, proof (AP2's Apply takes about this)
MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
SAVED_OPTIONS = (
    "htmode",
    "noscan",
    "legacy_rates",
    "supported_rates",
    "basic_rate",
    "channel",
    "channels",
    "txpower",
    "disabled",
)


@dataclass(frozen=True)
class StepRequest:
    radio: str
    modes: tuple[Mode, ...]
    channels: tuple[int, ...]
    powers: tuple[int, ...] = ()
    advance: Advance = "timer"
    dwell_s: int = 60
    station: str | None = None  # rejoin only
    rejoin_limit_s: int = 120


@dataclass(frozen=True)
class Step:
    index: int  # 1-based, as shown
    mode: Mode
    channel: int
    txpower_dbm: int | None


def _check(req: StepRequest, limits: RadioLimits) -> None:
    if not req.modes:
        raise ValueError(NO_MODE)
    if not req.channels:
        raise ValueError(NO_CHANNEL)
    for ch in sorted(set(req.channels)):
        if ch not in limits.channels:
            raise ValueError(f"Channel {ch} is not allowed in country {limits.country}")
    top = max(limits.txpower_dbm, default=0)
    for p in sorted(set(req.powers)):
        if p > top:
            raise ValueError(f"{p} dBm is above this radio's maximum of {top} dBm")
        if p not in limits.txpower_dbm:
            raise ValueError(f"{p} dBm is not a TX power this radio offers")
    if not DWELL_S[0] <= req.dwell_s <= DWELL_S[1]:
        raise ValueError(f"A dwell is {DWELL_S[0]} to {DWELL_S[1]} s")
    if req.advance == "rejoin":
        if not req.station:
            raise ValueError("Choose the station that re-joins")
        if not MAC.fullmatch(req.station.lower()):
            raise ValueError(f"{req.station!r} is not a MAC address")
        if not REJOIN_LIMIT_S[0] <= req.rejoin_limit_s <= REJOIN_LIMIT_S[1]:
            raise ValueError(f"A re-join limit is {REJOIN_LIMIT_S[0]} to {REJOIN_LIMIT_S[1]} s")


def expand_steps(req: StepRequest, limits: RadioLimits) -> tuple[Step, ...]:
    """The steps, numbered; ValueError naming the first problem before anything is planned."""
    _check(req, limits)
    modes = [m for m in MODES if m in req.modes]
    powers: list[int | None] = list(sorted(set(req.powers))) or [None]
    combos = [(m, c, p) for m in modes for c in sorted(set(req.channels)) for p in powers]
    if len(combos) > MAX_STEPS:
        raise ValueError(f"{len(combos)} steps; at most {MAX_STEPS}")
    return tuple(Step(i, m, c, p) for i, (m, c, p) in enumerate(combos, 1))


def step_request(step: Step, radio: str) -> RadioRequest:
    return RadioRequest(
        radio=radio,
        modes=ModeSelection.of(step.mode),
        channels=ChannelSelection.of(step.channel),
        txpower=TxPowerSetting("fixed", step.txpower_dbm) if step.txpower_dbm is not None else None,
    )


def saved_options(uci: Mapping[str, str], radio: str) -> dict[str, str | None]:
    """The radio's options a step-through changes, as they are now; None for an absent one."""
    return {name: uci.get(f"wireless.{radio}.{name}") for name in SAVED_OPTIONS}


def saved_ops(radio: str, saved: Mapping[str, str | None]) -> list[UciOp]:
    """Back to the saved options: set what was there, delete what was absent."""
    p = f"wireless.{radio}"
    return [
        UciOp("set", f"{p}.{name}", saved[name])
        if saved.get(name) is not None
        else UciOp("delete", f"{p}.{name}")
        for name in SAVED_OPTIONS
    ]


def joined(get_clients: Mapping[str, Any], mac: str) -> bool:
    """The station is on the AP again: listed by hostapd with `assoc` and `authorized`."""
    clients = {str(k).lower(): v for k, v in (get_clients.get("clients") or {}).items()}
    client = clients.get(mac.lower())
    return isinstance(client, dict) and bool(client.get("assoc")) and bool(client.get("authorized"))
