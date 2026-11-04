"""Build the simulator overlays in tests/fixtures/sim from the AP2 recordings.

AP1 becomes a router on air with one station, AP3 gets its own name and address,
and "new" is the router the Add-router wizard adds in tests and e2e (192.168.1.4).

    uv run python tools/make_sim_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openwrtgui.probe.commands import (
    DHCP_LAN,
    IFACE_DUMP,
    ROOT_PASSWORD_STATE,
    SYSTEM_BOARD,
    WIRELESS_STATUS,
    iwinfo_assoclist,
    iwinfo_info,
)

ROOT = Path(__file__).resolve().parents[1]
AP2 = ROOT / "tests" / "fixtures" / "ap2" / "commands.json"
SIM = ROOT / "tests" / "fixtures" / "sim"

ROUTERS = [
    {
        "id": "ap1",
        "name": "AP1 · bench",
        "host": "192.168.1.1",
        "base": "ap2",
        "overlay": "ap1.overlay.json",
        "auth": "key",
    },
    {
        "id": "ap2",
        "name": "AP2 · office",
        "host": "192.168.1.2",
        "base": "ap2",
        "overlay": None,
        "auth": "key",
    },
    {
        "id": "ap3",
        "name": "AP3 · QA stands",
        "host": "192.168.1.3",
        "base": "ap2",
        "overlay": "ap3.overlay.json",
        "auth": "none",
    },
    {
        "id": "new",
        "name": "",
        "host": "192.168.1.4",
        "base": "ap2",
        "overlay": "new.json",
        "auth": "none",
        "password": "sim-password",
        "wizard_only": True,
    },
]


def _json(entry: dict[str, Any]) -> Any:
    return json.loads(entry["stdout"])


def _entry(data: Any) -> dict[str, Any]:
    return {"stdout": json.dumps(data, indent="\t") + "\n", "exit": 0}


def _board(base: dict[str, Any], hostname: str) -> dict[str, Any]:
    board = _json(base[SYSTEM_BOARD])
    board["hostname"] = hostname
    return _entry(board)


def _lan(base: dict[str, Any], address: str) -> dict[str, Any]:
    dump = _json(base[IFACE_DUMP])
    for iface in dump["interface"]:
        if iface["interface"] == "lan":
            iface["ipv4-address"] = [{"address": address, "mask": 24}]
    return _entry(dump)


def build() -> None:
    base = json.loads(AP2.read_text(encoding="utf-8"))
    wireless = _json(base[WIRELESS_STATUS])
    radio = wireless["radio0"]
    radio.update({"up": True, "disabled": False})
    radio["config"].update({"disabled": False, "htmode": "HT20", "txpower": 20})
    radio["interfaces"] = [
        {
            "section": "default_radio0",
            "ifname": "phy0-ap0",
            "config": {
                "ssid": "OpenWrt",
                "encryption": "psk2",
                "key": "<hidden>",
                "mode": "ap",
                "network": ["lan"],
            },
            "vlans": [],
            "stations": [],
        }
    ]
    dhcp = _json(base[DHCP_LAN])
    dhcp["values"].pop("ignore", None)
    ap1 = {
        SYSTEM_BOARD: _board(base, "AP1"),
        WIRELESS_STATUS: _entry(wireless),
        IFACE_DUMP: _lan(base, "192.168.1.1"),
        DHCP_LAN: _entry(dhcp),
        iwinfo_info("phy0-ap0"): _entry(
            {
                "phy": "phy0",
                "ssid": "OpenWrt",
                "bssid": "00:0C:43:76:20:18",
                "country": "IL",
                "mode": "Master",
                "channel": 1,
                "center_chan1": 1,
                "frequency": 2412,
                "txpower": 20,
                "quality": 0,
                "quality_max": 70,
                "bitrate": 65000,
                "htmode": "HT20",
                "hwmode": "n",
                "hwmodes": ["b", "g", "n"],
                "htmodes": ["HT20", "HT40"],
                "encryption": {"enabled": True, "wpa": [2], "authentication": ["psk"], "ciphers": ["ccmp"]},
            }
        ),
        iwinfo_assoclist("phy0-ap0"): _entry(
            {
                "results": [
                    {
                        "mac": "F4:12:FA:F3:57:68",
                        "signal": -52,
                        "signal_avg": -53,
                        "noise": 0,
                        "inactive": 40,
                        "connected_time": 11520,
                        "thr": 38000,
                        "authorized": True,
                        "rx": {"rate": 54000, "ht": False},
                        "tx": {"rate": 65000, "mcs": 7, "ht": True, "40mhz": False},
                    }
                ]
            }
        ),
    }
    ap3 = {SYSTEM_BOARD: _board(base, "AP3"), IFACE_DUMP: _lan(base, "192.168.1.3")}
    new = {
        IFACE_DUMP: _lan(base, "192.168.1.4"),
        ROOT_PASSWORD_STATE: {"stdout": "set\n", "exit": 0},
    }
    SIM.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("routers.json", ROUTERS),
        ("ap1.overlay.json", ap1),
        ("ap3.overlay.json", ap3),
        ("new.json", new),
    ):
        (SIM / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote simulator fixtures to {SIM}")


if __name__ == "__main__":
    build()
