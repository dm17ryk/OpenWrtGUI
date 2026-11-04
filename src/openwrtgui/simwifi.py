"""A simulated router's wireless: uci state, reloads, and the iw / iwinfo / hostapd / rpcd answers.

The simulator (e2e, screenshots, demos) and tests use it. It answers the exact commands the app sends;
anything it does not know falls back to the recorded router output. One station (the bench panel) is
associated while the radio is up.
"""

from __future__ import annotations

import json
import math
import re
import shlex
from typing import Any

from openwrtgui.transport.base import CommandResult
from openwrtgui.wifi.compile import shell_quote
from openwrtgui.wifi.parse import parse_uci_show

STATION_MAC = "f4:12:fa:f3:57:68"
STATION_NAME = "panel"
STATION_IP = "192.168.1.30"
NO_DEVICE = "command failed: No such device (-19)\n"
_UBUS = re.compile(r"^ubus call (\S+) (\S+)(?: '(.*)')?$")
_BOOL_OPTIONS = {"disabled", "legacy_rates", "noscan"}
_INT_OPTIONS = {"cell_density", "txpower"}
_PHY_INFO = (
    "Wiphy {phy}\n\twiphy index: 0\n\tmax # scan SSIDs: 4\n\tBand 1:\n\t\tCapabilities: 0x2ce\n"
    "\t\t\tHT20/HT40\n\t\tHT TX/RX MCS rate indexes supported: 0-15\n"
    "\t\tBitrates (non-HT):\n\t\t\t* 1.0 Mbps\n\t\t\t* 2.0 Mbps (short preamble supported)\n"
    "\t\tFrequencies:\n\t\t\t* 2412.0 MHz [1] (20.0 dBm)\n\tsupported interface modes:\n"
    "\t\t * managed\n\t\t * AP\n\t\t * monitor\n"
)


def _ok(stdout: str = "", command: str = "") -> CommandResult:
    return CommandResult(command, stdout, "", 0)


def _fail(stderr: str, status: int = 1, command: str = "") -> CommandResult:
    return CommandResult(command, "", stderr, status)


class SimWifi:
    def __init__(self, uci_text: str, *, phy: str = "phy0", bssid: str = "02:00:00:00:00:01") -> None:
        self._committed = parse_uci_show(uci_text)
        self._staged = dict(self._committed)
        self._phy = phy
        self._bssid = bssid
        self._up = {r: self._opt(r, "disabled") != "1" for r in self._radios()}
        self._ifindex = 12
        self._monitor = False
        self._away = 0  # samples the station stays away after del_client
        self._tick = 0
        self._sessions = 0

    # ---------------------------------------------------------------- uci state
    def _radios(self) -> list[str]:
        return [
            k.split(".")[1] for k, v in self._committed.items() if k.count(".") == 1 and v == "wifi-device"
        ]

    def _opt(self, section: str, name: str, default: str | None = None) -> str | None:
        return self._committed.get(f"wireless.{section}.{name}", default)

    def _ifaces(self, radio: str) -> list[tuple[str, str]]:
        """(ifname, section) of the radio's SSIDs, named as netifd names them (phy0-ap0, phy0-ap1, …)."""
        sections = [
            k.split(".")[1]
            for k, v in self._committed.items()
            if k.count(".") == 1 and v == "wifi-iface" and self._opt(k.split(".")[1], "device") == radio
        ]
        return [(f"{self._phy}-ap{i}", s) for i, s in enumerate(sections)]

    def _iface(self, ifname: str) -> tuple[str, str] | None:
        for radio in self._radios():
            if not self._up.get(radio):
                continue
            for name, section in self._ifaces(radio):
                if name == ifname:
                    return radio, section
        return None

    def _channel(self, radio: str) -> int:
        value = self._opt(radio, "channel", "1") or "1"
        if value.isdigit():
            return int(value)
        first = re.match(r"\d+", self._opt(radio, "channels", "") or "")
        return int(first.group(0)) if first else 1

    def _width(self, radio: str) -> tuple[int, bool]:
        htmode = self._opt(radio, "htmode", "HT20")
        return (40, False) if htmode == "HT40" else (20, htmode == "NOHT")

    def _txpower(self, radio: str) -> int:
        return int(self._opt(radio, "txpower", "20") or 20)

    def _basic_mbps(self, radio: str) -> float:
        basic = self._opt(radio, "basic_rate")
        if basic:
            return min(int(r) for r in basic.split()) / 1000
        return 1.0 if self._opt(radio, "legacy_rates") == "1" else 6.0

    def _station_rates(self, radio: str) -> tuple[str, str]:
        htmode = self._opt(radio, "htmode", "HT20")
        supported = self._opt(radio, "supported_rates") or ""
        if htmode == "NOHT":
            only_cck = bool(supported) and all(int(r) <= 11000 for r in supported.split())
            rate = "11.0 MBit/s" if only_cck else "54.0 MBit/s"
            return rate, rate
        tx = "65.0 MBit/s MCS 7" + (" 40MHz" if htmode == "HT40" else "")
        return tx, "54.0 MBit/s"

    # ---------------------------------------------------------------- entry point
    def answer(self, command: str) -> CommandResult | None:
        out: list[str] = []
        for line in command.split("\n"):
            for part in re.split(r"; | && ", line):
                part = part.strip()
                if not part:
                    continue
                result = self._one(part)
                if result is None:
                    return None
                out.append(result.stdout)
                if not result.ok:
                    return CommandResult(command, "".join(out), result.stderr, result.exit_status)
        return CommandResult(command, "".join(out), "", 0)

    def _one(self, p: str) -> CommandResult | None:
        if p.startswith("echo "):
            return _ok(p[5:] + "\n")
        if p in ("uci -q show wireless", "uci show wireless", "uci show"):
            return _ok(self._show())
        if p.startswith("uci "):
            return self._uci(p)
        if m := re.fullmatch(r"wifi (down|up) (\S+)", p):
            return self._wifi(m.group(1), m.group(2))
        if m := _UBUS.match(p):
            return self._ubus(m.group(1), m.group(2), json.loads(m.group(3) or "{}"))
        if p == f"iw phy {self._phy} info":
            return _ok(_PHY_INFO.format(phy=self._phy))
        if p == "iw dev":
            return _ok(self._iw_dev())
        if m := re.fullmatch(r"iw dev (\S+) (info|station dump|survey dump|set bitrates.*)", p):
            return self._iw(m.group(1), m.group(2))
        if p == f"iw phy {self._phy} interface add owgmon0 type monitor":
            self._monitor = True
            return _ok()
        if p == "ip link set owgmon0 up":
            return _ok() if self._monitor else _fail("ip: SIOCGIFFLAGS: No such device\n")
        if p == "ip link del owgmon0":
            self._monitor = False
            return _ok()
        if p.startswith("timeout 5 tcpdump -i owgmon0 "):
            return self._beacons(p)
        if p.startswith(f"cat /sys/kernel/debug/ieee80211/{self._phy}/statistics/dot11ACKFailureCount"):
            return _ok(f"{3 * self._tick}\n")
        return None

    def _show(self) -> str:
        lines = []
        for key, value in self._committed.items():
            lines.append(f"{key}={value}" if key.count(".") == 1 else f"{key}={shell_quote(value)}")
        return "\n".join(lines) + "\n"

    def _uci(self, p: str) -> CommandResult | None:
        tokens = [t for t in shlex.split(p) if t != "-q"]
        if tokens[1:] == ["commit", "wireless"]:
            self._committed = dict(self._staged)
            return _ok()
        if len(tokens) != 3 or not tokens[2].startswith("wireless."):
            return None
        verb, arg = tokens[1], tokens[2]
        if verb == "delete":
            self._staged.pop(arg, None)
            return _ok()
        path, _, value = arg.partition("=")
        if verb == "set":
            self._staged[path] = value
        elif verb == "add_list":
            self._staged[path] = f"{self._staged.get(path, '')} {value}".strip()
        else:
            return None
        return _ok()

    def _wifi(self, action: str, radio: str) -> CommandResult:
        if radio not in self._up:
            return _fail(f"Device {radio} not found\n")
        if action == "down":
            self._up[radio] = False
        else:
            self._up[radio] = self._opt(radio, "disabled") != "1"
            if self._up[radio]:
                self._ifindex += 1
        return _ok()

    # ---------------------------------------------------------------- ubus
    def _ubus(self, obj: str, method: str, args: dict[str, Any]) -> CommandResult | None:
        if (obj, method) == ("network.wireless", "status"):
            return _ok(json.dumps(self._status(), indent="\t") + "\n")
        if obj == "iwinfo":
            return self._iwinfo(method, str(args.get("device", "")))
        if (obj, method) == ("luci-rpc", "getHostHints"):
            hint = {"name": STATION_NAME, "ipaddrs": [STATION_IP], "ip6addrs": []}
            return _ok(json.dumps({STATION_MAC.upper(): hint}))
        if obj.startswith("hostapd.") and method == "del_client":
            if self._iface(obj.removeprefix("hostapd.")) is None:
                return _fail("Command failed: Not found\n", 4)
            if str(args.get("addr", "")).lower() == STATION_MAC:
                self._away = max(3, int(args.get("ban_time", 0)) // 1000)
            return _ok("{}\n")
        if obj == "session":
            return self._session(method, args)
        return None

    def _status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for radio in self._radios():
            config: dict[str, Any] = {}
            for key, value in self._committed.items():
                prefix = f"wireless.{radio}."
                if key.startswith(prefix):
                    name = key[len(prefix) :]
                    config[name] = (
                        value == "1"
                        if name in _BOOL_OPTIONS
                        else int(value)
                        if name in _INT_OPTIONS
                        else value
                    )
            config.setdefault("disabled", False)
            interfaces = []
            if self._up[radio]:
                for ifname, section in self._ifaces(radio):
                    iface = {
                        "ssid": self._opt(section, "ssid", ""),
                        "encryption": self._opt(section, "encryption", "none"),
                        "key": "<hidden>",
                        "mode": self._opt(section, "mode", "ap"),
                        "network": (self._opt(section, "network", "") or "").split(),
                    }
                    interfaces.append(
                        {"section": section, "ifname": ifname, "config": iface, "vlans": [], "stations": []}
                    )
            out[radio] = {
                "up": self._up[radio],
                "pending": False,
                "autostart": True,
                "disabled": config["disabled"],
                "retry_setup_failed": False,
                "config": config,
                "interfaces": interfaces,
            }
        return out

    def _iwinfo(self, method: str, device: str) -> CommandResult | None:
        if method == "freqlist":
            ch = self._channel("radio0")
            results: list[dict[str, Any]] = [
                {"mhz": 2407 + 5 * c, "channel": c, "restricted": False, "active": c == ch}
                for c in range(1, 14)
            ]
            results.append({"mhz": 2484, "channel": 14, "restricted": True, "active": False})
            return _ok(json.dumps({"results": results}))
        if method == "txpowerlist":
            powers = [{"dbm": d, "mw": round(10 ** (d / 10)), "active": d == 20} for d in range(21)]
            return _ok(json.dumps({"results": powers}))
        if method == "countrylist":
            return _ok(json.dumps({"results": [{"code": "IL", "country": "Israel", "active": True}]}))
        found = self._iface(device)
        if method in ("info", "assoclist") and found is None:
            return _fail("Command failed: Not found\n", 4)
        if found is None:
            return None
        radio, section = found
        if method == "info":
            ch = self._channel(radio)
            info = {
                "phy": self._phy,
                "ssid": self._opt(section, "ssid", ""),
                "bssid": self._bssid.upper(),
                "country": self._opt(radio, "country", "00"),
                "mode": "Master",
                "channel": ch,
                "center_chan1": ch,
                "frequency": 2407 + 5 * ch,
                "txpower": self._txpower(radio),
                "quality": 0,
                "quality_max": 70,
                "bitrate": 65000,
                "htmode": self._opt(radio, "htmode", "HT20"),
                "hwmode": "n",
                "hwmodes": ["b", "g", "n"],
                "htmodes": ["HT20", "HT40"],
            }
            return _ok(json.dumps(info, indent="\t") + "\n")
        if method == "assoclist":
            return _ok(json.dumps({"results": self._assoc(radio)}, indent="\t") + "\n")
        return None

    def _present(self) -> bool:
        if self._away > 0:
            self._away -= 1
            return False
        return True

    def _assoc(self, radio: str) -> list[dict[str, Any]]:
        if not self._present():
            return []
        tx, rx = self._station_rates(radio)
        ht = "MCS" in tx
        return [
            {
                "mac": STATION_MAC.upper(),
                "signal": -52,
                "signal_avg": -53,
                "noise": 0,
                "inactive": 40,
                "connected_time": 11520,
                "thr": 38000,
                "authorized": True,
                "rx": {"rate": int(float(rx.split()[0]) * 1000), "ht": False},
                "tx": {
                    "rate": int(float(tx.split()[0]) * 1000),
                    "mcs": 7 if ht else 0,
                    "ht": ht,
                    "40mhz": "40MHz" in tx,
                },
            }
        ]

    def _session(self, method: str, args: dict[str, Any]) -> CommandResult:
        if method == "create":
            self._sessions += 1
            sid = f"sim-{self._sessions}"
            return _ok(
                json.dumps(
                    {"ubus_rpc_session": sid, "timeout": int(args.get("timeout", 300)), "expires": 300}
                )
            )
        return _ok("{}\n" if method != "list" else json.dumps({}))

    # ---------------------------------------------------------------- iw
    def _iw_dev(self) -> str:
        lines: list[str] = []
        for radio in self._radios():
            if self._monitor:
                lines += [
                    "\tInterface owgmon0",
                    "\t\tifindex 99",
                    f"\t\taddr {self._bssid}",
                    "\t\ttype monitor",
                ]
            if self._up[radio]:
                for ifname, section in self._ifaces(radio):
                    lines += [
                        f"\tInterface {ifname}",
                        f"\t\tifindex {self._ifindex}",
                        f"\t\taddr {self._bssid}",
                        f"\t\tssid {self._opt(section, 'ssid', '')}",
                        "\t\ttype AP",
                        f"\t\t{self._channel_line(radio)}",
                    ]
        return "phy#0\n" + "\n".join(lines) + "\n" if lines else ""

    def _channel_line(self, radio: str) -> str:
        ch = self._channel(radio)
        freq = 2407 + 5 * ch
        width, no_ht = self._width(radio)
        center = freq + 10 if width == 40 else freq
        no_ht_text = " (no HT)" if no_ht else ""
        return f"channel {ch} ({freq} MHz), width: {width} MHz{no_ht_text}, center1: {center} MHz"

    def _iw(self, ifname: str, what: str) -> CommandResult:
        found = self._iface(ifname)
        if found is None:
            return _fail(NO_DEVICE, 237)
        radio, section = found
        if what == "info":
            return _ok(
                f"Interface {ifname}\n\tifindex {self._ifindex}\n\twdev 0x1\n\taddr {self._bssid}\n"
                f"\tssid {self._opt(section, 'ssid', '')}\n\ttype AP\n\twiphy 0\n"
                f"\t{self._channel_line(radio)}\n\ttxpower {self._txpower(radio):.2f} dBm\n"
            )
        if what == "station dump":
            self._tick += 1
            return _ok(self._station_dump(radio) if self._present() else "")
        if what == "survey dump":
            freq = 2407 + 5 * self._channel(radio)
            t = self._tick
            return _ok(
                f"Survey data from {ifname}\n\tfrequency:\t{freq} MHz [in use]\n"
                f"\tchannel active time:\t{1000 * t} ms\n\tchannel busy time:\t{230 * t} ms\n"
            )
        return _ok()  # set bitrates

    def _station_dump(self, radio: str) -> str:
        t = self._tick
        s = -52 + round(6 * math.sin(t / 10))
        tx, rx = self._station_rates(radio)
        ifname = self._ifaces(radio)[0][0]
        return (
            f"Station {STATION_MAC} (on {ifname})\n\tinactive time:\t40 ms\n\trx bytes:\t{1000 * t}\n"
            f"\trx packets:\t{50 * t}\n\ttx bytes:\t{1500 * t}\n\ttx packets:\t{60 * t}\n"
            f"\ttx retries:\t{3 * t}\n\ttx failed:\t{t // 10}\n\trx drop misc:\t0\n"
            f"\tsignal:  \t{s} [{s - 2}, {s - 3}] dBm\n\tsignal avg:\t{s - 1} [{s - 3}, {s - 4}] dBm\n"
            f"\ttx bitrate:\t{tx}\n\trx bitrate:\t{rx}\n\texpected throughput:\t38.0Mbps\n"
            f"\tconnected time:\t{11520 + t} seconds\n"
        )

    def _beacons(self, p: str) -> CommandResult:
        radio = self._radios()[0]
        if not (self._monitor and self._up[radio] and f"wlan addr2 {self._bssid}" in p):
            return CommandResult(p, "", "0 packets captured\n", 124)
        ch = self._channel(radio)
        rate = self._basic_mbps(radio)
        ssid = self._opt(self._ifaces(radio)[0][1], "ssid", "")
        line = (
            f"10:00:00.{{n:06d}} {rate:.1f} Mb/s {2407 + 5 * ch} MHz 11g -38dBm signal antenna 0 "
            f"Beacon ({ssid}) [6.0* 9.0 12.0* 18.0 24.0* 36.0 48.0 54.0 Mbit] ESS CH: {ch}, PRIVACY"
        )
        return _ok("".join(line.format(n=102400 * i + 1) + "\n" for i in range(5)))
