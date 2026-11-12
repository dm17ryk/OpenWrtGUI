"""The simulated air around a router (v0.7 plan Task 7): neighbour networks for channel analysis, the survey
of every channel, the temporary scan interface and frame windows on the monitor interface.

It sits in front of SimWifi and answers only commands it knows whole; the RF sampler's compound read still
goes to SimWifi, whose own-channel counters this survey repeats, so RF live reads as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openwrtgui.rf.air import FRAME_WINDOW, MONITOR_FLAGS, SCAN_IF
from openwrtgui.simwifi import NO_DEVICE, STATION_MAC, SimWifi
from openwrtgui.transport.base import CommandResult

CHANNELS = range(1, 14)
SCAN_DWELL_MS = 110  # a passive scan's dwell per channel
BUSY = "command failed: Device or resource busy (-16)\n"


@dataclass(frozen=True)
class SimNetwork:
    bssid: str
    ssid: str  # as iw prints it (\xNN escapes)
    channel: int
    signal_dbm: int
    security: str  # "", "WPA2", "WPA2/WPA3", "WPA3"
    secondary: str | None = None  # "above" / "below"


SIM_NETWORKS = (
    SimNetwork("02:00:00:00:a0:01", "net-01", 1, -48, "WPA2"),
    SimNetwork("02:00:00:00:a0:02", "", 3, -71, "WPA2"),  # hidden
    SimNetwork("02:00:00:00:a0:03", "net-03", 6, -63, ""),
    SimNetwork("02:00:00:00:a0:04", "net-04 caf\\xc3\\xa9", 6, -77, "WPA2"),
    SimNetwork("02:00:00:00:a0:05", "net-05", 11, -58, "WPA2/WPA3", "below"),
    SimNetwork("02:00:00:00:a0:06", "net-06", 13, -80, "WPA3"),
)
_SUITES = {"WPA2": "PSK", "WPA2/WPA3": "PSK SAE", "WPA3": "SAE"}


def _ok(stdout: str = "", stderr: str = "", status: int = 0) -> CommandResult:
    return CommandResult("", stdout, stderr, status)


def _freq(channel: int) -> int:
    return 2407 + 5 * channel


def _bss_text(n: SimNetwork, ifname: str) -> str:
    privacy = " Privacy" if n.security else ""
    lines = [
        f"BSS {n.bssid}(on {ifname})",
        f"\tfreq: {_freq(n.channel)}.0",
        "\tbeacon interval: 100 TUs",
        f"\tcapability: ESS{privacy} ShortSlotTime (0x0411)",
        f"\tsignal: {n.signal_dbm:.2f} dBm",
        "\tlast seen: 160 ms ago",
        f"\tSSID: {n.ssid}",
        "\tSupported rates: 1.0* 2.0* 5.5* 11.0* 6.0 9.0 12.0 18.0 ",
        f"\tDS Parameter set: channel {n.channel}",
    ]
    if n.security:
        lines += [
            "\tRSN:\t * Version: 1",
            "\t\t * Group cipher: CCMP",
            "\t\t * Pairwise ciphers: CCMP",
            f"\t\t * Authentication suites: {_SUITES[n.security]}",
        ]
    lines += [
        "\tHT operation:",
        f"\t\t * primary channel: {n.channel}",
        f"\t\t * secondary channel offset: {n.secondary or 'no secondary'}",
    ]
    return "\n".join(lines) + "\n"


def _mb(rate: str) -> str:
    """SimWifi's iw station rate ("65.0 MBit/s MCS 7 40MHz") as tcpdump prints a radiotap rate."""
    mbps = rate.split()[0]
    if m := re.search(r"MCS (\d+)", rate):
        width = "40 MHz" if "40MHz" in rate else "20 MHz"
        return f"{mbps} Mb/s MCS {m.group(1)} {width} short GI"
    return f"{mbps} Mb/s"


class SimAir:
    def __init__(self, wifi: SimWifi) -> None:
        self._wifi = wifi
        self._scan_if = False
        # what scans added per channel (active, busy); other channels start from a fixed history
        self._scanned = {ch: (5000 * ch, 1000 * ch) for ch in CHANNELS}

    # ---------------------------------------------------------------- entry point
    def answer(self, command: str) -> CommandResult | None:
        out: list[str] = []
        for part in re.split(r"; | && ", command):
            part = part.strip()
            result = self._one(part) if part else _ok()
            if result is None:
                return None
            out.append(result.stdout)
            if not result.ok:
                return CommandResult(command, "".join(out), result.stderr, result.exit_status)
        return CommandResult(command, "".join(out), "", 0)

    def _one(self, p: str) -> CommandResult | None:
        phy = self._wifi.phy
        if p == f"iw dev {SCAN_IF} del 2>/dev/null":
            self._scan_if = False
            return _ok()
        if p == f"iw phy {phy} interface add {SCAN_IF} type managed":
            self._scan_if = True
            return _ok()
        if p == f"ip link set {SCAN_IF} up":
            return _ok() if self._scan_if else _ok("", "ip: SIOCGIFFLAGS: No such device\n", 1)
        if p == f"iw dev {SCAN_IF} del":
            if not self._scan_if:
                return _ok("", NO_DEVICE, 237)
            self._scan_if = False
            return _ok()
        if p == f"iw dev {SCAN_IF} info":
            if not self._scan_if:
                return _ok("", NO_DEVICE, 237)
            return _ok(f"Interface {SCAN_IF}\n\tifindex 10\n\ttype managed\n\twiphy {phy[3:]}\n")
        if m := re.fullmatch(r"iw dev (\S+) scan( ap-force)? passive", p):
            return self._scan(m.group(1), ap_force=m.group(2) is not None)
        if m := re.fullmatch(r"iw dev (\S+) survey dump", p):
            return self._survey(m.group(1))
        if p == MONITOR_FLAGS or re.fullmatch(r"iw dev owgmon0 set channel \d+", p):
            return _ok() if self._wifi.monitor else _ok("", NO_DEVICE, 237)
        if p == FRAME_WINDOW:
            return self._frames()
        return None

    # ---------------------------------------------------------------- scan and survey
    def _ap(self) -> tuple[str, int, str, str] | None:
        return self._wifi.on_air()

    def _known(self, ifname: str) -> bool:
        ap = self._ap()
        return (ifname == SCAN_IF and self._scan_if) or (ap is not None and ifname == ap[2])

    def _scan(self, ifname: str, *, ap_force: bool) -> CommandResult:
        if not self._known(ifname):
            return _ok("", NO_DEVICE, 237)
        ap = self._ap()
        if ap is not None and ifname == ap[2] and not ap_force:
            return _ok("", BUSY, 240)  # mac80211 scans on an AP interface only with ap-force
        for ch in CHANNELS:
            active, busy = self._scanned[ch]
            share = 20 + (7 * ch) % 41  # 20-60 % busy while the radio listened there
            self._scanned[ch] = (active + SCAN_DWELL_MS, busy + SCAN_DWELL_MS * share // 100)
        heard = list(SIM_NETWORKS)
        if ap is not None:
            _radio, channel, _if, ssid = ap
            heard.insert(0, SimNetwork(self._wifi.bssid, ssid, channel, -20, "WPA2"))
        return _ok("".join(_bss_text(n, ifname) for n in heard))

    def _counters(self, ch: int) -> tuple[int, int]:
        active, busy = self._scanned[ch]
        ap = self._ap()
        if ap is not None and ap[1] == ch:  # SimWifi's own-channel counters, as RF live reads them
            t = self._wifi.tick
            return 1000 * t + active - 5000 * ch, 230 * t + busy - 1000 * ch
        return active, busy

    def _survey(self, ifname: str) -> CommandResult:
        if not self._known(ifname):
            return _ok("", NO_DEVICE, 237)
        out = []
        for ch in CHANNELS:  # rt2800 marks every channel "[in use]" (spec O4)
            active, busy = self._counters(ch)
            out.append(
                f"Survey data from {ifname}\n\tfrequency:\t\t\t{_freq(ch)} MHz [in use]\n"
                f"\tchannel active time:\t\t{active} ms\n\tchannel busy time:\t\t{busy} ms\n"
                f"\textension channel busy time:\t{busy // 10} ms\n"
            )
        return _ok("".join(out))

    # ---------------------------------------------------------------- frames
    def _frames(self) -> CommandResult:
        if not self._wifi.monitor:
            return _ok("", "tcpdump: owgmon0: No such device exists\n", 1)
        lines: list[str] = []
        n = 0

        def stamp() -> str:
            nonlocal n
            n += 1
            return f"10:00:01.{n * 1013:06d}"

        ap = self._ap()
        if ap is not None:
            radio, channel, _if, _ssid = ap
            tx_rate, rx_rate = self._wifi.station_rates(radio)
            own = self._wifi.bssid
            rx_head = f"1234567us tsft {_mb(rx_rate)} {_freq(channel)} MHz 11g"
            for i in range(40):
                retry = "Retry " if i % 10 == 0 else ""
                lines.append(
                    f"{stamp()} {rx_head} {-48 - i % 13}dBm signal antenna 0 {retry}44us "
                    f"BSSID:{own} SA:{STATION_MAC} DA:{own} Data IV"
                )
            for _ in range(60):
                lines.append(
                    f"{stamp()} {_mb(tx_rate)} antenna 0 44us "
                    f"DA:{STATION_MAC} BSSID:{own} SA:{own} QoS Data IV"
                )
        for net in SIM_NETWORKS[:2]:  # neighbours' beacons, and two that arrived broken
            b = net.bssid
            lines.append(
                f"{stamp()} 1.0 Mb/s 2437 MHz 11b {net.signal_dbm}dBm signal antenna 0 "
                f"BSSID:{b} DA:ff:ff:ff:ff:ff:ff SA:{b} Beacon ({net.ssid or ''})"
            )
            lines.append(
                f"{stamp()} bad-fcs 1.0 Mb/s 2437 MHz 11b -88dBm signal antenna 0 "
                f"BSSID:{b} DA:ff:ff:ff:ff:ff:ff SA:{b} Beacon ({net.ssid or ''})"
            )
        count = len(lines)
        stderr = (
            f"{count} packets captured\n{count} packets received by filter\n0 packets dropped by kernel\n"
        )
        return _ok("".join(line + "\n" for line in lines), stderr, 124)
