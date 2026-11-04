"""/etc/board.json: the router's own hardware description (what LuCI reads too)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SwitchPort:
    num: int
    role: str | None
    label: str | None
    cpu: bool
    device: str | None


@dataclass(frozen=True)
class Led:
    name: str
    sysfs: str


@dataclass(frozen=True)
class RadioBand:
    phy: str
    band: str
    modes: tuple[str, ...]
    max_width: int | None


@dataclass(frozen=True)
class BoardInfo:
    model_id: str
    model_name: str
    switch_name: str | None
    ports: tuple[SwitchPort, ...]
    leds: tuple[Led, ...]
    radios: tuple[RadioBand, ...]
    default_network: dict[str, Any]


def _port(raw: dict[str, Any]) -> SwitchPort:
    device = raw.get("device")
    role = raw.get("role")
    if device:
        label: str | None = f"CPU ({device})"
    elif role == "lan" and raw.get("index") is not None:
        label = f"LAN{raw['index']}"
    elif role == "wan":
        label = "WAN"
    else:
        label = None
    return SwitchPort(num=int(raw["num"]), role=role, label=label, cpu=bool(device), device=device)


def parse_board_json(text: str) -> BoardInfo:
    data = json.loads(text)
    model = data.get("model", {})
    switches = data.get("switch", {})
    switch_name = next(iter(switches), None)
    ports = tuple(_port(p) for p in switches[switch_name].get("ports", [])) if switch_name else ()
    leds = tuple(Led(name=v.get("name", k), sysfs=v.get("sysfs", "")) for k, v in data.get("led", {}).items())
    radios = tuple(
        RadioBand(phy=phy, band=band, modes=tuple(b.get("modes", [])), max_width=b.get("max_width"))
        for phy, entry in data.get("wlan", {}).items()
        for band, b in entry.get("info", {}).get("bands", {}).items()
    )
    return BoardInfo(
        model_id=model.get("id", ""),
        model_name=model.get("name", ""),
        switch_name=switch_name,
        ports=ports,
        leds=leds,
        radios=radios,
        default_network=data.get("network", {}),
    )
