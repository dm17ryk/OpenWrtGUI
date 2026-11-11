"""LEDs as LuCI's LED page reads them (plan D9): `luci getLEDs` and the system `led` sections."""

from __future__ import annotations

import json

from openwrtgui.system.leds import (
    NETDEV_MODES,
    TRIGGER_OPTIONS,
    LedInfo,
    LedRow,
    parse_led_sections,
    parse_leds,
)

TRIGGERS = ["none", "timer", "heartbeat", "default-on", "netdev", "switch0", "phy0rx"]


def test_led_parse() -> None:
    leds = parse_leds(
        json.dumps(
            {
                "green:wifi": {
                    "triggers": TRIGGERS,
                    "active_trigger": "none",
                    "brightness": 0,
                    "max_brightness": 1,
                },
                "green:lan": {
                    "triggers": TRIGGERS,
                    "active_trigger": "switch0",
                    "brightness": 1,
                    "max_brightness": 1,
                },
            }
        )
    )
    assert leds == [
        LedInfo(
            sysfs="green:lan", triggers=tuple(TRIGGERS), active="switch0", brightness=1, max_brightness=1
        ),
        LedInfo(sysfs="green:wifi", triggers=tuple(TRIGGERS), active="none", brightness=0, max_brightness=1),
    ]


def test_led_sections_of_ap2() -> None:
    rows = parse_led_sections(
        "system.cfg01e48a=system\n"
        "system.cfg01e48a.hostname='OpenWrt'\n"
        "system.led_lan=led\n"
        "system.led_lan.name='lan'\n"
        "system.led_lan.sysfs='green:lan'\n"
        "system.led_lan.trigger='switch0'\n"
        "system.led_lan.port_mask='0x0f'\n"
        "system.cfg0b3c4d=led\n"
        "system.cfg0b3c4d.name='wan'\n"
        "system.cfg0b3c4d.sysfs='green:internet'\n"
        "system.cfg0b3c4d.trigger='netdev'\n"
        "system.cfg0b3c4d.dev='eth0.2'\n"
        "system.cfg0b3c4d.mode='link tx rx'\n"
        "system.cfg0c=led\n"
        "system.cfg0c.sysfs='green:4g'\n"
        "system.cfg0c.default='1'\n"
    )
    lan, wan, plain = rows
    assert lan == LedRow(
        section="led_lan",
        name="lan",
        sysfs="green:lan",
        trigger="switch0",
        default=None,
        delayon=None,
        delayoff=None,
        inverted=None,
        dev=None,
        mode=(),
        port_mask="0x0f",
        speed_mask=None,
    )
    assert (wan.trigger, wan.dev, wan.mode) == ("netdev", "eth0.2", ("link", "tx", "rx"))
    # no trigger option is `none`, as /etc/init.d/led reads it
    assert (plain.trigger, plain.default, plain.name) == ("none", True, "")


def test_trigger_options_follow_luci() -> None:
    assert TRIGGER_OPTIONS["none"] == ("default",)
    assert TRIGGER_OPTIONS["timer"] == ("delayon", "delayoff")
    assert TRIGGER_OPTIONS["heartbeat"] == ("inverted",)
    assert TRIGGER_OPTIONS["netdev"] == ("dev", "mode")
    assert TRIGGER_OPTIONS["switch0"] == ("port_mask", "speed_mask")
    assert "default-on" not in TRIGGER_OPTIONS
    assert {"link", "tx", "rx", "link_1000", "full_duplex"} <= set(NETDEV_MODES)
