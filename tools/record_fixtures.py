"""Record a router's read-only output into a fixture file under tests/fixtures/.

Read-only: it sends only the commands of one set and refuses any other host than AP2 (192.168.1.2)
unless --allow-other is given. Wi-Fi keys, passwords and IMEIs are replaced before writing.

    uv run python tools/record_fixtures.py --host 192.168.1.2 \
        --identity C:/Essence_SC/home/.ssh/id_rsa --set probe --out tests/fixtures/ap2

Sets: probe (the self-description and status probes, commands.json), wifi-parked (the Wi-Fi
config and limits, wifi_parked.json), wifi-on (the radio while it is on air, wifi_on.json; needs
an AP interface up on phy0).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from openwrtgui.guard.audit import mask
from openwrtgui.probe.commands import DESCRIBE_COMMANDS, STATUS_COMMANDS, wireless_validate
from openwrtgui.rf.parse import parse_station_dump
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key
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
    ),
}
FILES = {"probe": "commands.json", "wifi-parked": "wifi_parked.json", "wifi-on": "wifi_on.json"}
_IMEI = re.compile(r"\b\d{15}\b")


class Runner(Protocol):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult: ...


def sanitize(text: str) -> str:
    """The audit log's masking (uci `.key='…'` and JSON `"key": "…"`), plus IMEIs."""
    return _IMEI.sub("<imei>", mask(text, ()))


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


async def run_set(t: Runner, commands: tuple[str, ...]) -> dict[str, dict[str, object]]:
    recorded: dict[str, dict[str, object]] = {}
    for command in commands:
        r = await t.run(command)
        entry: dict[str, object] = {"stdout": sanitize(r.stdout), "exit": r.exit_status}
        if r.stderr:
            entry["stderr"] = sanitize(r.stderr)
        recorded[command] = entry
    return recorded


async def record(host: str, identity: Path, known_hosts: Path, name: str) -> dict[str, dict[str, object]]:
    info = await fetch_host_key(host)
    print(f"{host} host key {info.type} {info.fingerprint}")
    keys = HostKeyStore(known_hosts)
    keys.pin(host, 22, info)
    t = await SshTransport.connect(host, 22, "root", host_keys=keys, key_paths=[identity])
    try:
        commands = await wifi_on_commands(t) if name == "wifi-on" else SETS[name]
        return await run_set(t, commands)
    finally:
        await t.close()


def out_file(out: Path, name: str) -> Path:
    """--out is the file, or a folder that gets the set's usual file name."""
    return out if out.suffix == ".json" else out / FILES[name]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=AP2)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", dest="name", choices=sorted(FILES), default="probe")
    ap.add_argument("--allow-other", action="store_true")
    args = ap.parse_args(argv)
    if args.host != AP2 and not args.allow_other:
        print(f"refusing {args.host}: only AP2 ({AP2}) without --allow-other", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        recorded = asyncio.run(record(args.host, args.identity, Path(tmp) / "known_hosts", args.name))
    target = out_file(args.out, args.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(recorded)} recordings to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
