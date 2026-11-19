"""Port statistics (spec 7.8 Phase 2; v1.2a R5-R6): each switch port's packets, bytes and errors from the MIB
counters `swconfig dev <switch> show` prints. One read; the router's counters are never cleared."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.ports.parse import parse_port_mib, parse_swconfig_show
from openwrtgui.probe.board import SwitchPort
from openwrtgui.transport.base import CommandResult

Direction = Literal["rx", "tx"]
Kind = Literal["packets", "bytes", "errors"]

# AP2's mt7620 names (good packets, good octets, error packets). Other drivers' names show under All counters.
KNOWN: Mapping[str, tuple[Direction, Kind]] = {
    "RxGPC": ("rx", "packets"),
    "RxGOC": ("rx", "bytes"),
    "RxEPC1": ("rx", "errors"),
    "RxEPC2": ("rx", "errors"),
    "TxGPC": ("tx", "packets"),
    "TxGOC": ("tx", "bytes"),
    "TxEPC": ("tx", "errors"),
}

NO_SWITCH = "This router has no swconfig switch, so it has no port counters here."
READ_FAILED = "Could not read the switch counters: {detail}"


class PortTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    rx_packets: int | None
    rx_bytes: int | None
    rx_errors: int | None
    tx_packets: int | None
    tx_bytes: int | None
    tx_errors: int | None


class PortCounters(BaseModel):
    model_config = ConfigDict(frozen=True)

    num: int
    label: str
    link: bool
    speed_mbps: int | None
    totals: PortTotals
    raw: dict[str, int]


class PortStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    switch: str | None
    read_at: float  # Unix seconds of the read: rates come from two reads
    ports: list[PortCounters]
    note: str | None = None


def totals(raw: Mapping[str, int]) -> PortTotals:
    """The known names added per column; a column with no known counter is None."""
    sums: dict[str, int] = {}
    for name, value in raw.items():
        if name in KNOWN:
            direction, kind = KNOWN[name]
            key = f"{direction}_{kind}"
            sums[key] = sums.get(key, 0) + value
    return PortTotals(
        rx_packets=sums.get("rx_packets"),
        rx_bytes=sums.get("rx_bytes"),
        rx_errors=sums.get("rx_errors"),
        tx_packets=sums.get("tx_packets"),
        tx_bytes=sums.get("tx_bytes"),
        tx_errors=sums.get("tx_errors"),
    )


def _label(port: SwitchPort, labels: Mapping[int, str]) -> str:
    if port.cpu:
        return "CPU"
    return labels.get(port.num) or port.label or f"port {port.num}"  # as the Ports screen names it


def port_stats(
    switch: str | None,
    ports: Sequence[SwitchPort],
    labels: Mapping[int, str],
    show: CommandResult | None,
    read_at: float,
) -> PortStats:
    """The board's ports with their counters, from one `show` (None when the router has no switch)."""
    if switch is None or show is None:
        return PortStats(switch=None, read_at=read_at, ports=[], note=NO_SWITCH)
    if not show.ok:
        detail = next(
            (line.strip() for line in show.stderr.splitlines() if line.strip()), f"exit {show.exit_status}"
        )
        return PortStats(switch=switch, read_at=read_at, ports=[], note=READ_FAILED.format(detail=detail))
    live = {p.num: p for p in parse_swconfig_show(switch, show.stdout).ports}
    mib = parse_port_mib(show.stdout)
    rows = []
    for port in sorted(ports, key=lambda p: (p.cpu, _label(p, labels))):  # as the Ports screen orders them
        state = live.get(port.num)
        raw = mib.get(port.num, {})
        rows.append(
            PortCounters(
                num=port.num,
                label=_label(port, labels),
                link=bool(state and state.link),
                speed_mbps=state.speed_mbps if state else None,
                totals=totals(raw),
                raw=raw,
            )
        )
    return PortStats(switch=switch, read_at=read_at, ports=rows)
