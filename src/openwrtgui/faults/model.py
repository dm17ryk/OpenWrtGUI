"""Faults on a target device (spec 7.7): what is asked, what is armed, what the router can do."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

FaultKind = Literal["link_down", "isolate", "block", "netem", "deauth", "ban", "ap_down"]
Flow = Literal["rtp_in", "sip_in", "rtp_out", "all_in", "all_out", "blackout"]
Family = Literal["netdev", "bridge"]


@dataclass(frozen=True)
class FaultTarget:
    name: str | None
    mac: str | None
    ip: str | None
    via: str | None  # the AP ifname of a Wi-Fi station, "wired", or unknown
    # where the fault's hooks go: the station's AP interface, or the lan bridge's wired member
    device: str | None


@dataclass(frozen=True)
class TargetRef:
    mac: str | None
    ip: str | None


@dataclass(frozen=True)
class NetemParams:
    delay_ms: int = 0
    jitter_ms: int = 0
    distribution: Literal["uniform", "normal", "pareto", "paretonormal"] = "uniform"
    loss_pct: float = 0
    reorder_pct: float = 0
    duplicate_pct: float = 0
    direction: Literal["to", "from", "both"] = "to"


@dataclass(frozen=True)
class FaultRequest:
    kind: FaultKind
    target: TargetRef
    flow: Flow | None = None
    loss: int = 100
    netem: NetemParams | None = None
    port: int | None = None
    ban_s: int | None = None
    hold_s: int | None = None


@dataclass(frozen=True)
class ArmedFault:
    id: str
    kind: FaultKind
    summary: str
    target: FaultTarget
    device: str | None
    clear: tuple[str, ...]
    armed_at: datetime
    until: datetime | None


@dataclass(frozen=True)
class FaultCaps:
    family: Family | None
    distributions: frozenset[str]
    ifb: bool
    conntrack: bool
    # the root qdisc that keeps netem to the target's traffic: prio, or ets with every band strict
    band: Literal["prio", "ets"] | None = "prio"
    netem: bool = True
