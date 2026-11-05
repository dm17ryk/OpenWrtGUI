"""What swconfig says about a switch (live), and the switch sections of `/etc/config/network`."""

from __future__ import annotations

from dataclasses import dataclass

Members = tuple[tuple[int, bool], ...]  # (port, tagged), ascending


@dataclass(frozen=True)
class SwitchPortLive:
    num: int
    enabled: bool | None  # None: swconfig answers "???" (not switchable)
    pvid: int | None
    link: bool
    speed_mbps: int | None
    full_duplex: bool | None
    mirror_rx: bool
    mirror_tx: bool


@dataclass(frozen=True)
class SwitchVlanLive:
    vlan: int
    vid: int | None
    members: Members


@dataclass(frozen=True)
class SwitchLive:
    name: str
    enable_vlan: bool | None
    mirror_monitor_port: int | None
    ports: tuple[SwitchPortLive, ...]
    vlans: tuple[SwitchVlanLive, ...]


@dataclass(frozen=True)
class SwitchHelp:
    ports: int
    cpu_port: int | None
    vlans: int
    port_attrs: frozenset[str]
    global_attrs: frozenset[str]


@dataclass(frozen=True)
class SwitchVlanConf:
    section: str
    device: str
    vlan: int
    vid: int | None
    members: Members


@dataclass(frozen=True)
class SwitchConf:
    section: str
    name: str
    mirror_monitor_port: int | None


@dataclass(frozen=True)
class SwitchPortConf:
    section: str
    device: str
    port: int
    mirror_rx: bool
    mirror_tx: bool
