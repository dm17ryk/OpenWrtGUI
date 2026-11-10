"""System › LEDs (v0.6c plan D9): the LEDs and their triggers as `ubus call luci getLEDs` gives them, and the
`system` `led` sections that /etc/init.d/led applies. Options per trigger follow LuCI's trigger plugins."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from openwrtgui.system.access import flag
from openwrtgui.uci import parse_uci_show

# LuCI's led-trigger plugins (none, timer, heartbeat, netdev) and the swconfig trigger AP2's led_lan uses
TRIGGER_OPTIONS: dict[str, tuple[str, ...]] = {
    "none": ("default",),
    "timer": ("delayon", "delayoff"),
    "heartbeat": ("inverted",),
    "netdev": ("dev", "mode"),
    "switch0": ("port_mask", "speed_mask"),
    "switch1": ("port_mask", "speed_mask"),
}
ALL_OPTIONS = ("default", "delayon", "delayoff", "inverted", "dev", "mode", "port_mask", "speed_mask")
NETDEV_MODES = (
    "link",
    "link_10",
    "link_100",
    "link_1000",
    "link_2500",
    "link_5000",
    "link_10000",
    "half_duplex",
    "full_duplex",
    "tx",
    "rx",
)


class LedInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    sysfs: str
    triggers: tuple[str, ...]
    active: str | None
    brightness: int
    max_brightness: int


class LedRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: str | None  # None: a new section
    name: str
    sysfs: str
    trigger: str
    default: bool | None = None
    delayon: int | None = None
    delayoff: int | None = None
    inverted: bool | None = None
    dev: str | None = None
    mode: tuple[str, ...] = ()
    port_mask: str | None = None
    speed_mask: str | None = None


def parse_leds(json_text: str) -> list[LedInfo]:
    raw = json.loads(json_text or "{}")
    out: list[LedInfo] = []
    for sysfs, info in sorted(raw.items()):
        if not isinstance(info, dict):
            continue
        out.append(
            LedInfo(
                sysfs=sysfs,
                triggers=tuple(str(t) for t in info.get("triggers", [])),
                active=info.get("active_trigger"),
                brightness=int(info.get("brightness", 0)),
                max_brightness=int(info.get("max_brightness", 0)),
            )
        )
    return out


def _int(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None


def parse_led_sections(uci_system_show: str) -> list[LedRow]:
    """Every `led` section of `uci -X show system`, in the router's order; no trigger means `none`."""
    shown = parse_uci_show(uci_system_show)
    rows: list[LedRow] = []
    for path, value in shown.items():
        if path.count(".") != 1 or value != "led":
            continue
        section = path.split(".", 1)[1]

        def get(option: str, base: str = path) -> str | None:
            return shown.get(f"{base}.{option}")

        rows.append(
            LedRow(
                section=section,
                name=get("name") or "",
                sysfs=get("sysfs") or "",
                trigger=get("trigger") or "none",
                default=None if get("default") is None else flag(get("default"), False),
                delayon=_int(get("delayon")),
                delayoff=_int(get("delayoff")),
                inverted=None if get("inverted") is None else flag(get("inverted"), False),
                dev=get("dev"),
                mode=tuple((get("mode") or "").split()),
                port_mask=get("port_mask"),
                speed_mask=get("speed_mask"),
            )
        )
    return rows
