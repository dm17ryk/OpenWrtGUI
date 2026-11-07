"""A router's live status for the dashboard, read through ubus."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openwrtgui.probe.commands import FAULT_RECORDS
from openwrtgui.transport.base import Transport, ubus_call

LOAD_SCALE = 65536


@dataclass(frozen=True)
class StationInfo:
    mac: str
    signal_dbm: int
    tx_mbps: float
    rx_mbps: float
    connected_s: int


@dataclass(frozen=True)
class SsidInfo:
    name: str
    encryption: str
    ifname: str | None


@dataclass(frozen=True)
class RadioStatus:
    name: str
    band: str
    up: bool
    disabled: bool
    channel: str | None
    htmode: str | None
    txpower_dbm: int | None
    ssids: tuple[SsidInfo, ...]
    stations: tuple[StationInfo, ...]


@dataclass(frozen=True)
class InterfaceStatus:
    name: str
    up: bool
    proto: str
    ipv4: tuple[str, ...]


@dataclass(frozen=True)
class RouterStatus:
    read_at: datetime
    uptime_s: int
    load: tuple[float, float, float]
    mem_total_kb: int
    mem_available_kb: int
    radios: tuple[RadioStatus, ...]
    interfaces: tuple[InterfaceStatus, ...]
    dhcp_server_on: bool | None
    faults_armed: int | None = None  # the app's fault records in /tmp/owg (spec 7.1)


def _station(raw: dict[str, Any]) -> StationInfo:
    return StationInfo(
        mac=str(raw.get("mac", "")).lower(),
        signal_dbm=int(raw.get("signal", 0)),
        tx_mbps=round(raw.get("tx", {}).get("rate", 0) / 1000, 1),
        rx_mbps=round(raw.get("rx", {}).get("rate", 0) / 1000, 1),
        connected_s=int(raw.get("connected_time", 0)),
    )


async def _radio(t: Transport, name: str, raw: dict[str, Any]) -> RadioStatus:
    config = raw.get("config", {})
    up = bool(raw.get("up"))
    channel = config.get("channel")
    htmode = config.get("htmode")
    txpower = config.get("txpower")
    ssids: list[SsidInfo] = []
    stations: list[StationInfo] = []
    for iface in raw.get("interfaces", []):
        icfg = iface.get("config", {})
        ifname = iface.get("ifname")
        ssids.append(SsidInfo(str(icfg.get("ssid", "")), str(icfg.get("encryption", "none")), ifname))
        if up and ifname:
            info = await ubus_call(t, "iwinfo", "info", {"device": ifname}) or {}
            channel = info.get("channel", channel)
            htmode = info.get("htmode", htmode)
            txpower = info.get("txpower", txpower)
            assoc = await ubus_call(t, "iwinfo", "assoclist", {"device": ifname}) or {}
            stations.extend(_station(s) for s in assoc.get("results", []))
    return RadioStatus(
        name=name,
        band=str(config.get("band", "")),
        up=up,
        disabled=bool(raw.get("disabled")),
        channel=str(channel) if channel is not None else None,
        htmode=htmode,
        txpower_dbm=int(txpower) if txpower is not None else None,
        ssids=tuple(ssids),
        stations=tuple(stations),
    )


def _interface(raw: dict[str, Any]) -> InterfaceStatus:
    addrs = tuple(f"{a['address']}/{a['mask']}" for a in raw.get("ipv4-address") or [])
    return InterfaceStatus(
        str(raw.get("interface", "")), bool(raw.get("up")), str(raw.get("proto", "")), addrs
    )


async def read_status(t: Transport) -> RouterStatus:
    info = await ubus_call(t, "system", "info") or {}
    wireless = await ubus_call(t, "network.wireless", "status") or {}
    dump = await ubus_call(t, "network.interface", "dump") or {}
    dhcp = await ubus_call(t, "uci", "get", {"config": "dhcp", "section": "lan"})
    load = [round(v / LOAD_SCALE, 2) for v in (info.get("load") or [0, 0, 0])[:3]]
    memory = info.get("memory", {})
    radios = [await _radio(t, name, raw) for name, raw in wireless.items() if isinstance(raw, dict)]
    dhcp_on = None if dhcp is None else dhcp.get("values", {}).get("ignore") != "1"
    records = await t.run(FAULT_RECORDS)
    # no record file: cat exits 1; a router that cannot answer at all: unknown
    armed = (
        sum(1 for line in records.stdout.splitlines() if line.strip())
        if records.exit_status in (0, 1)
        else None
    )
    return RouterStatus(
        read_at=datetime.now().astimezone(),
        uptime_s=int(info.get("uptime", 0)),
        load=(load[0], load[1], load[2]),
        mem_total_kb=int(memory.get("total", 0)) // 1024,
        mem_available_kb=int(memory.get("available", 0)) // 1024,
        radios=tuple(radios),
        interfaces=tuple(_interface(i) for i in dump.get("interface", [])),
        dhcp_server_on=dhcp_on,
        faults_armed=armed,
    )


def ssids_on_air(status: RouterStatus) -> list[str]:
    return [s.name for r in status.radios if r.up for s in r.ssids]
