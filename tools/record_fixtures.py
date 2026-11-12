"""Record a router's read-only output into a fixture file under tests/fixtures/.

Read-only: it sends only the commands of one set and refuses any other host than AP2 (192.168.1.2)
unless --allow-other is given. Wi-Fi keys, passwords and IMEIs are replaced before writing.

    uv run python tools/record_fixtures.py --host 192.168.1.2 \
        --identity C:/Essence_SC/home/.ssh/id_rsa --set probe --out tests/fixtures/ap2

The router's host key is checked against --known-hosts (default ~/.ssh/known_hosts) and never
taken on trust: connect with ssh once and check the fingerprint first.

Sets: probe (the self-description and status probes, commands.json), wifi-parked (the Wi-Fi
config and limits, wifi_parked.json), wifi-on (the radio while it is on air, wifi_on.json; needs
an AP interface up on phy0), network (interfaces, DHCP, leases, routes and the switch, network.json),
firewall (fw4's config, the nft ruleset, tc, and what the router can do for faults, firewall.json),
discovery (the overlay listing, packages, every config, the keep list, flash partitions, RAM and /tmp,
and the firmware hash with its run time, discovery.json; run it only while Bench Guard is clear),
lte (the modem: uqmi serving system, signal and operating mode, netifd status, the image's AT probe and
AT queries on every ttyUSB, lte.json; IMEI and ICCID are masked; never the IMEI read itself).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Collection
from pathlib import Path
from typing import Protocol

from openwrtgui.discovery import commands as dc
from openwrtgui.discovery.firmware import parse_proc_mtd
from openwrtgui.faults.commands import CAPABILITY_READS, FAMILY_CHECKS
from openwrtgui.fw.commands import FIREWALL_READS, FW4_PRINT
from openwrtgui.guard.audit import mask
from openwrtgui.lte import commands as lc
from openwrtgui.lte.at import IDENTITY, find_at_port
from openwrtgui.net.commands import INTERFACE_DUMP, network_reads
from openwrtgui.probe.commands import DESCRIBE_COMMANDS, FAULT_RECORDS, STATUS_COMMANDS, wireless_validate
from openwrtgui.rf.parse import parse_station_dump
from openwrtgui.system import commands as sc
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.wifi.parse import parse_iw_dev

AP2 = "192.168.1.2"
PHY = "phy0"
SETS: dict[str, tuple[str, ...]] = {
    "probe": (*DESCRIBE_COMMANDS, *STATUS_COMMANDS, wireless_validate("radio0")),
    "wifi-parked": (
        "uci -q show wireless",
        'ubus call iwinfo freqlist \'{"device":"radio0"}\'',
        'ubus call iwinfo txpowerlist \'{"device":"radio0"}\'',
        'ubus call iwinfo countrylist \'{"device":"radio0"}\'',
        f"iw phy {PHY} info",
        "iw dev",
        "uci show",
        # read_wifi's own reads, so the parked recording replays on its own
        "ubus call network.wireless status",
        'ubus call iwinfo phyname \'{"section":"radio0"}\'',
    ),
    # The Network & DHCP and Ports screens' reads (AP2's switch is switch0)
    "network": network_reads("switch0"),
    # The Firewall screen's reads and what the router can do for faults (reads; `nft -c` commits nothing)
    "firewall": (*FIREWALL_READS, *CAPABILITY_READS, FW4_PRINT, FAULT_RECORDS, *FAMILY_CHECKS.values()),
    # the System screen's reads; of the backup only its size (the archive holds secrets)
    "system": (
        sc.BOARD,
        sc.INFO,
        sc.UCI_SYSTEM,
        sc.RC_LIST,
        sc.TIMEZONES,
        sc.TOP,
        sc.DMESG,
        sc.logread(100),
        sc.RC_LOCAL,
        sc.CRONTAB,
        sc.TZ_FILE,
        sc.LIVE,
        sc.CONNTRACK,
        sc.BACKUP_SIZE,
    ),
    # v0.6c: public keys only; the password digest is compared live, never recorded
    "access": (
        sc.UCI_DROPBEAR,
        sc.UCI_UHTTPD,
        sc.UCI_RPCD,
        sc.KEYS_READ,
        sc.APK_KEYS,
        sc.OPKG_KEYS,
        sc.LEDS,
        sc.NET_DEVICES,
        sc.MOUNTS,
        sc.DF,
        sc.HAS_BLOCK,
        sc.KEPT,
        sc.BACKUP_LIST,
        sc.LISTENERS,
        INTERFACE_DUMP,
    ),
}
FILES = {
    "probe": "commands.json",
    "wifi-parked": "wifi_parked.json",
    "wifi-on": "wifi_on.json",
    "network": "network.json",
    "firewall": "firewall.json",
    "discovery": "discovery.json",
    "lte": "lte.json",
    "system": "system.json",
    "access": "access.json",
}
LTE_LIST = "ls /dev/ttyUSB* /dev/cdc-wdm*"
# the AT reads the LTE screen makes on the AT port (only queries: nothing changes the modem)
LTE_AT_READS: tuple[tuple[str, ...], ...] = (
    *((command,) for command in IDENTITY),  # one exec each, as the app reads them
    ("AT+COPS?",),
    ("AT+BMMODODR?",),
    ("AT+CSQ",),
)
# The bench image's firmware length (uImage + kernel + squashfs up to its end, before the padding): the bytes
# the firmware check hashes on the router's "firmware" partition
BENCH_FIRMWARE_LEN = 11255254
DISCOVERY_READS = (
    dc.OVERLAY_LS,
    dc.APK_DB,
    dc.CONFIG_LIST,
    dc.SYSUPGRADE_LIST,
    dc.PROC_MTD,
    dc.MEMINFO,
    dc.DF_TMP,
    "ubus -v list system",
    "command -v sha256sum dd head",
)
_IMEI = re.compile(r"\b\d{15}\b")
_ICCID = re.compile(r"\b\d{18,20}\b")
# A public key names the PC it logs in from, and its comment a person and a PC; this repo is public. Each key
# in a recording becomes one of these throwaways (made for the recorder, their private parts discarded): the
# n-th distinct key of a type gets the n-th throwaway, so a recording keeps how many keys there were.
PLACEHOLDER_KEYS: dict[str, tuple[str, ...]] = {
    "ssh-rsa": (
        "AAAAB3NzaC1yc2EAAAADAQABAAABAQDkuVGF3sVWo1QoDphEpeUMG2dTbO52IbAh3weBtyT2yoKLMHoMTv6OuWf3EPShQgPKLko37wg"
        "VJSJxPrhMnHJy627TPAULUM3VAvr4EbPsTSkG0Or9bZYzxnVZN37TU2IUScZykhbmIWErrBtCw5JMfKC83hHO6GBt37XPv60uCw9GeG"
        "E5s5NhESfRs+FWVNToLccMBF1R+q0jZB4l8tmVFEtirlx0KaOf1bg69PfwPfNw3GdHfRH6YsOyDlmq6S+69OylkW6hcAC9kXhOuNa2S"
        "aJ7agkJEn6aNK6GGt/0dbLJkROjQvstCsDbBl3hK/mSl1CVsA4M3uct6upcJYO3",
        "AAAAB3NzaC1yc2EAAAADAQABAAABAQChVjFKSOurvga57S45fJ66rXoXxIbwxqfYH6XKfHzRqk0ZpZ2EZjHzoqwQ1C/4g2puc/qlRo4"
        "/DQgqITeqz/bzd/eTaGWL0RrRSgG0hUyKbHvAt0qUkMn84cLvmy03xN1e6AnTkQOSQgC3d5807oCerkPjyjAQOuXOjhQxavkcwxhiTV"
        "+9xj75xjIckPBYxo2wPeHBo9hwepAoKlgwS8DHwp5cPvhBG2jvQWObLSSSfUHUb8Deo1KA6cw0fm23ny0OjpElo1QGawEWqRgEhXa4r"
        "Q/7Bp15B7rQPCmbozKjE/4gy1iZ69OYZVJIIxmSEcP692RE2VAuuzGRu1oc0R0h",
    ),
    "ssh-ed25519": (
        "AAAAC3NzaC1lZDI1NTE5AAAAIBoghaIZ+QAK8HYJ5BzQBS8fr0z1Jz8c0gLP20NlIEQi",
        "AAAAC3NzaC1lZDI1NTE5AAAAIEeN2gEjAeD8LVkj/gTQDSxOcPCD5IPg87e/h53vQKLn",
    ),
}
_KEY_LINE = re.compile(
    r"^(?P<options>.*?)(?P<type>ssh-(?:rsa|dss|ed25519)|ecdsa-sha2-nistp\d+|sk-\S+@openssh\.com)"
    r" (?P<blob>[A-Za-z0-9+/=]{16,})(?P<comment> +\S.*)?$",
    re.M,
)


def _replace_keys(text: str) -> str:
    seen: dict[str, list[str]] = {}

    def one(m: re.Match[str]) -> str:
        key_type = m.group("type") if m.group("type") in PLACEHOLDER_KEYS else "ssh-ed25519"
        distinct = seen.setdefault(key_type, [])
        if m.group("blob") not in distinct:
            distinct.append(m.group("blob"))
        throwaways = PLACEHOLDER_KEYS[key_type]
        blob = throwaways[distinct.index(m.group("blob")) % len(throwaways)]
        comment = (m.group("comment") or "").strip()
        if comment:
            comment = " openwrtgui@pc" if comment.startswith("openwrtgui@") else " user@pc"
        return f"{m.group('options')}{key_type} {blob}{comment}"

    return _KEY_LINE.sub(one, text)


class Runner(Protocol):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult: ...


def sanitize(text: str) -> str:
    """The audit log's masking (uci `.key='…'` and JSON `"key": "…"`), plus IMEIs and public keys."""
    return _replace_keys(_IMEI.sub("<imei>", _ICCID.sub("<iccid>", mask(text, ()))))


# Air recordings (v0.7 plan D14): a scan or a monitor window names the neighbours' networks and addresses, and
# this repo is public. Each neighbour becomes a placeholder, the same one in every command of a file.
# Not \b: tcpdump's labels "DA:" and "BSSID:" end in hex letters, and "DA:ff:ff:ff:ff:ff" must not match.
_MAC = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}(?![:0-9a-fA-F])")
_SSID_LINE = re.compile(r"^(\s*SSID: )(.*)$", re.M)
# The SSID ends at the ")" before the rates (" [") or at the end of a trimmed line: it may itself hold ")".
_FRAME_SSID = re.compile(
    r"\b(Beacon|Probe Response|Probe Request|Assoc Request|ReAssoc Request) \((.*?)\)(?= \[|$)", re.M
)
_PLACEHOLDER_MAC = "02:00:00:00:"
_PLACEHOLDER_SSID = re.compile(r"net-\d{2,}")
_IW_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")


def _iw_text(raw: str) -> str:
    """An SSID as iw prints it (`\\xNN` for every byte that is not printable) back to text."""
    data = _IW_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), raw).encode("latin-1", "replace")
    return data.decode("utf-8", "replace")


def _placeholder(kind: str, value: str, names: dict[str, str]) -> str:
    key = f"{kind}:{value}"
    if key not in names:
        n = sum(1 for k in names if k.startswith(f"{kind}:")) + 1
        names[key] = f"{_PLACEHOLDER_MAC}{n // 256:02x}:{n % 256:02x}" if kind == "mac" else f"net-{n:02d}"
    return names[key]


# What an air recording keeps (v0.7 review I7): a scan's lines the parser reads, and each frame line up to
# its frame type and SSID. WPS names, serial numbers, mesh IDs and the payload tcpdump -v prints (IP
# addresses, mDNS host names) never reach the file.
_SCAN_TOP = (
    "freq",
    "signal",
    "last seen",
    "SSID",
    "capability",
    "RSN",
    "WPA",
    "HT operation",
    "DS Parameter set",
)
_SCAN_NESTED = {
    "RSN": ("Authentication suites",),
    "WPA": ("Authentication suites",),
    "HT operation": ("primary channel", "secondary channel offset"),
}
_FRAME_ADDR = re.compile(r"\b(?:SA|TA|DA|RA|BSSID):[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}")
_FRAME_TYPE = re.compile(
    r"\s+((?:QoS )?(?:Data|Null)|Beacon|Probe Request|Probe Response|(?:Re)?Assoc (?:Request|Response)"
    r"|Authentication|DeAuthentication|Disassociation|Action|Acknowledgment|Clear-To-Send|Request-To-Send"
    r"|Power Save-Poll|CF-End|BAR|BA)\b"
)
_WITH_SSID = ("Beacon", "Probe Request", "Probe Response", "Assoc Request", "ReAssoc Request")
_TCPDUMP_STATUS = re.compile(r"tcpdump: |\d+ packets? (?:captured|received by filter|dropped by kernel)")


def _trim_scan(text: str) -> str:
    out: list[str] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("BSS "):
            out.append(line)
            continue
        if line.startswith("\t") and not line.startswith("\t\t"):
            section = line.strip().split(":", 1)[0]
            if section in _SCAN_TOP:
                out.append(line.split("\t*")[0].rstrip() if section in _SCAN_NESTED else line)
            continue
        if any(key in line for key in _SCAN_NESTED.get(section, ())):
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


def _trim_frame(line: str) -> str | None:
    """A frame line up to its type (and SSID); a tcpdump status line as it is; anything else (the payload
    lines tcpdump -v prints under a frame) is dropped."""
    addrs = list(_FRAME_ADDR.finditer(line))
    if not addrs:
        return line if _TCPDUMP_STATUS.match(line) else None
    head, rest = line[: addrs[-1].end()], line[addrs[-1].end() :]
    m = _FRAME_TYPE.match(rest)
    if m is None:
        return head
    kind = m.group(1)
    if kind in _WITH_SSID and rest[m.end() :].startswith(" ("):
        body = rest[m.end() + 2 :]
        end = body.rfind(") [")
        ssid = body[: end if end >= 0 else body.rfind(")")]
        return f"{head} {kind} ({ssid})"
    return f"{head} {kind}"


def trim_air(command: str, text: str) -> str:
    """Only what the scan and frame parsers read, before sanitize_air replaces the neighbours' names."""
    if "tcpdump" in command:
        kept = (_trim_frame(line) for line in text.splitlines())
        return "".join(line + "\n" for line in kept if line is not None)
    if " scan" in command and "survey" not in command:
        return _trim_scan(text)
    return text


def sanitize_air(
    text: str, own_macs: Collection[str], own_ssids: Collection[str], names: dict[str, str]
) -> str:
    """Every MAC that is not the router's own, a group address or a placeholder becomes `02:00:00:00:NN:NN`;
    every SSID that is not the router's own becomes `net-NN`. `names` keeps the mapping across one file."""
    own = {m.lower() for m in own_macs}

    def mac(m: re.Match[str]) -> str:
        value = m.group(0).lower()
        if value in own or value.startswith(_PLACEHOLDER_MAC) or int(value[:2], 16) & 1:
            return m.group(0)
        return _placeholder("mac", value, names)

    def ssid(raw: str) -> str:
        kept = not raw.strip() or _PLACEHOLDER_SSID.fullmatch(raw) is not None
        if kept or raw in own_ssids or _iw_text(raw) in own_ssids:
            return raw
        return _placeholder("ssid", raw, names)

    text = _SSID_LINE.sub(lambda m: m.group(1) + ssid(m.group(2)), text)
    text = _FRAME_SSID.sub(lambda m: f"{m.group(1)} ({ssid(m.group(2))})", text)
    return _MAC.sub(mac, text)


async def wifi_on_commands(t: Runner) -> tuple[str, ...]:
    """The radio-on set: built from the AP interface on phy0 and the stations on it now."""
    ap = next(
        (i for i in parse_iw_dev((await t.run("iw dev")).stdout) if i.phy == 0 and i.type == "AP"), None
    )
    if ap is None:
        raise RuntimeError(f"no AP interface on {PHY}: the radio must be on air for --set wifi-on")
    stations = parse_station_dump((await t.run(f"iw dev {ap.ifname} station dump")).stdout)
    debug = f"/sys/kernel/debug/ieee80211/{PHY}"
    return (
        f"iw dev {ap.ifname} info",
        f"iw dev {ap.ifname} station dump",
        f"iw dev {ap.ifname} survey dump",
        f"cat {debug}/statistics/dot11ACKFailureCount",
        f"iw phy {PHY} info",
        "ubus -v list 'hostapd.*'",
        *(f"cat {debug}/netdev:{ap.ifname}/stations/{s.mac}/rc_stats_csv" for s in stations),
    )


async def discovery_commands(t: Runner) -> tuple[str, ...]:
    """Discovery's reads, every config `ls /etc/config` lists, and the firmware hash where there is a
    partition named firmware (reads only: about 11 MB of flash through sha256sum, seconds of CPU)."""
    listed = (await t.run(dc.CONFIG_LIST)).stdout.splitlines()
    configs = [c.strip() for c in listed if dc.CONFIG_NAME.fullmatch(c.strip())]
    index = parse_proc_mtd((await t.run(dc.PROC_MTD)).stdout).get("firmware")
    hashed = () if index is None else (dc.firmware_hash(index, BENCH_FIRMWARE_LEN),)
    return (*DISCOVERY_READS, *(dc.uci_show(c) for c in configs), *hashed)


async def lte_commands(t: Runner) -> tuple[str, ...]:
    """The LTE screen's reads (lte/commands.py), then `AT` to each tty in order up to the first that answers
    (as the app finds its AT port) and the AT reads on that port only. On AP2 (2026-11-09) ttyUSB3 never takes
    the bytes, and the image's dwr921-at-probe hung on it; a port after the AT port is never opened."""
    listed = (await t.run(LTE_LIST)).stdout.split()
    device = next((p for p in listed if lc.MODEM_DEVICE.fullmatch(p)), "/dev/cdc-wdm0")
    ports = sorted(p for p in listed if lc.AT_PORT.fullmatch(p))
    found = await find_at_port(t)  # type: ignore[arg-type]  # a Runner is all find_at_port uses
    probed = ports[: ports.index(found) + 1] if found in ports else ports
    reads = tuple(lc.at(found, *r) for r in LTE_AT_READS) if found else ()
    return (
        LTE_LIST,
        lc.SERVING(device),
        lc.SIGNAL(device),
        lc.OPMODE(device),
        lc.iface_status("lte"),
        lc.iface_status("lte_4"),
        lc.device_status("wwan0"),
        "cat /tmp/run/dwr921-qmi-state",
        *(lc.at(port, "AT") for port in probed),
        *reads,
    )


async def run_set(
    t: Runner, commands: tuple[str, ...], *, timed: frozenset[str] = frozenset()
) -> dict[str, dict[str, object]]:
    recorded: dict[str, dict[str, object]] = {}
    for command in commands:
        started = time.monotonic()
        r = await t.run(command, timeout=60.0 if command in timed else 15.0)
        entry: dict[str, object] = {"stdout": sanitize(r.stdout), "exit": r.exit_status}
        if r.stderr:
            entry["stderr"] = sanitize(r.stderr)
        if command in timed:
            entry["seconds"] = round(time.monotonic() - started, 2)
        recorded[command] = entry
    return recorded


async def record(host: str, identity: Path, known_hosts: Path, name: str) -> dict[str, dict[str, object]]:
    # The router's key must already be in known_hosts (checked by the user); never pinned here.
    t = await SshTransport.connect(
        host, 22, "root", host_keys=HostKeyStore(known_hosts), key_paths=[identity]
    )
    try:
        if name == "discovery":
            commands = await discovery_commands(t)
            return await run_set(t, commands, timed=frozenset(c for c in commands if c.startswith("dd ")))
        if name == "lte":  # microcom takes seconds each: timed, with the 60 s timeout
            commands = await lte_commands(t)
            slow = frozenset(c for c in commands if "microcom" in c)
            return await run_set(t, commands, timed=slow)
        commands = await wifi_on_commands(t) if name == "wifi-on" else SETS[name]
        return await run_set(t, commands)
    finally:
        await t.close()


def out_file(out: Path, name: str) -> Path:
    """--out is the file, or a folder that gets the set's usual file name."""
    return out if out.suffix == ".json" else out / FILES[name]


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=AP2)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--known-hosts", type=Path, default=Path.home() / ".ssh" / "known_hosts")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", dest="name", choices=sorted(FILES), default="probe")
    ap.add_argument("--allow-other", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.host != AP2 and not args.allow_other:
        print(f"refusing {args.host}: only AP2 ({AP2}) without --allow-other", file=sys.stderr)
        return 2
    recorded = asyncio.run(record(args.host, args.identity, args.known_hosts, args.name))
    target = out_file(args.out, args.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(recorded)} recordings to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
