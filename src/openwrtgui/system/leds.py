"""System › LEDs (v0.6c plan D9): the LEDs and their triggers as `ubus call luci getLEDs` gives them, and the
`system` `led` sections that /etc/init.d/led applies. Options per trigger follow LuCI's trigger plugins."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from openwrtgui.system.access import flag
from openwrtgui.uci import UciOp, parse_uci_show

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


class LedChange(BaseModel):
    """The LED actions as they should be: section None is new; a section left out is removed."""

    model_config = ConfigDict(frozen=True)

    rows: list[LedRow]


def _values(row: LedRow) -> dict[str, str | None]:
    def flag(v: bool | None) -> str | None:
        return None if v is None else ("1" if v else "0")

    return {
        "default": flag(row.default),
        "delayon": None if row.delayon is None else str(row.delayon),
        "delayoff": None if row.delayoff is None else str(row.delayoff),
        "inverted": flag(row.inverted),
        "dev": row.dev or None,
        "mode": " ".join(row.mode) or None,
        "port_mask": row.port_mask or None,
        "speed_mask": row.speed_mask or None,
    }


def _check_row(row: LedRow, by_name: dict[str, LedInfo], devices: list[str], router: str) -> None:
    from openwrtgui.system.commands import HEX_MASK, LED_NAME

    if row.name and not LED_NAME.fullmatch(row.name):
        raise ValueError(f"{row.name!r}: an LED name is 1-32 letters, digits, spaces, dots, colons or dashes")
    info = by_name.get(row.sysfs)
    if info is None:
        raise ValueError(f"No LED {row.sysfs} on {router}")
    if row.trigger != "none" and row.trigger not in info.triggers:
        raise ValueError(f"{row.sysfs} has no trigger {row.trigger}")
    allowed = TRIGGER_OPTIONS.get(row.trigger, ())
    for option in ("delayon", "delayoff"):
        value = getattr(row, option)
        if option in allowed and value is not None and not 1 <= value <= 10000:
            raise ValueError("A delay is 1-10000 ms")
    if "dev" in allowed and row.dev and row.dev not in devices:
        raise ValueError(f"No device {row.dev} on {router}")
    if "mode" in allowed and any(m not in NETDEV_MODES for m in row.mode):
        bad = next(m for m in row.mode if m not in NETDEV_MODES)
        raise ValueError(f"{bad!r} is not a netdev mode ({', '.join(NETDEV_MODES)})")
    for option in ("port_mask", "speed_mask"):
        value = getattr(row, option)
        if option in allowed and value and not HEX_MASK.fullmatch(value):
            raise ValueError(f"{value!r} is not a mask like 0x0f")


def led_ops(
    current: list[LedRow], change: LedChange, leds: list[LedInfo], devices: list[str], *, router_name: str
) -> list[UciOp]:
    """uci ops on the `system` led sections: only the trigger's own options are set, the rest deleted."""
    by_name = {info.sysfs: info for info in leds}
    seen: set[str] = set()
    for row in change.rows:
        _check_row(row, by_name, devices, router_name)
        if row.sysfs in seen:
            raise ValueError(f"Two LED actions for {row.sysfs}: the last would win")
        seen.add(row.sysfs)
    known = {r.section for r in current}
    ops: list[UciOp] = []
    for n, row in enumerate(change.rows, start=1):
        if row.section is not None and row.section not in known:
            raise ValueError(f"No LED action {row.section} on {router_name}")
        base = f"system.$led{n}" if row.section is None else f"system.{row.section}"
        if row.section is None:
            ops.append(UciOp("add", base, "led"))
        ops.append(UciOp("set", f"{base}.name", row.name) if row.name else UciOp("delete", f"{base}.name"))
        ops += [UciOp("set", f"{base}.sysfs", row.sysfs), UciOp("set", f"{base}.trigger", row.trigger)]
        allowed = TRIGGER_OPTIONS.get(row.trigger, ())
        for option, value in _values(row).items():
            if option in allowed and value is not None:
                ops.append(UciOp("set", f"{base}.{option}", value))
            else:
                ops.append(UciOp("delete", f"{base}.{option}"))
    kept = {row.section for row in change.rows if row.section is not None}
    ops += [UciOp("delete", f"system.{r.section}") for r in current if r.section not in kept]
    return ops
