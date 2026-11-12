"""AP2 air windows for the v0.7 test helpers (plan Tasks 3 and 17, D16).

HW-1, AP2 parked, nothing transmitted: a passive scan on a temporary managed interface, the survey before and
after, a 3 s window on a monitor interface set to channel 6 (other networks' frames), the monitor's flags.
Recorded to tests/fixtures/ap2/air.json with every neighbour MAC and SSID replaced (plan D14); both interfaces
are removed in a `finally`, and AP2's wireless config and interfaces must read exactly as before.

    uv run pytest -m hardware tests/hardware/test_ap2_air.py --router 192.168.1.2 --identity <key> \
        --allow-writes --txctl-told -v -k record

Run it only in a window the owner OK'd, with the parent session's "AP2 free, txctl told", Bench Guard clear,
never between 20:15 and 09:30.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
from ro_transport import ReadOnlyTransport

from openwrtgui.rf.air import (
    FRAME_WINDOW,
    MONITOR_FLAGS,
    SCAN_DEL,
    SCAN_IF,
    scan_add,
    scan_command,
    survey_command,
)
from openwrtgui.transport.ssh import SshTransport
from openwrtgui.wifi.monitor import DEL, MONITOR, add_command
from openwrtgui.wifi.parse import parse_iw_dev, parse_uci_show

pytestmark = pytest.mark.hardware

ROOT = Path(__file__).resolve().parents[2]
AIR = ROOT / "tests" / "fixtures" / "ap2" / "air.json"
MACADDRESS = "cat /sys/class/ieee80211/phy0/macaddress"
AFTER = " #after-scan"  # a key with '#' is never replayed as a command
MAC = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}(?![:0-9a-fA-F])")
FIRST = ("uci -q show wireless", "iw dev", MACADDRESS)
SCAN = (scan_add("phy0"), survey_command(SCAN_IF), scan_command(SCAN_IF, on_ap=False))
MONITOR_WINDOW = (
    add_command("phy0", clear_leftover=True),
    MONITOR_FLAGS,
    f"iw dev {MONITOR} set channel 6",
    FRAME_WINDOW,
)


def _recorder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", ROOT / "tools" / "record_fixtures.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


async def _found(t: SshTransport) -> tuple[str, str]:
    return (await t.run("uci -q show wireless")).stdout, (await t.run("iw dev")).stdout


async def test_record_parked_air(ap2_rw: SshTransport) -> None:
    t = ap2_rw
    rf = _recorder()
    wireless, iw_dev = await _found(t)
    assert parse_uci_show(wireless).get("wireless.radio0.disabled") == "1", "AP2's radio must be parked"
    assert not any(i.type == "AP" for i in parse_iw_dev(iw_dev)), "AP2 must have no AP interface"
    recorded: dict[str, dict[str, object]] = {}
    try:
        recorded |= await rf.run_set(t, FIRST)
        recorded |= await rf.run_set(t, SCAN, timed=frozenset({SCAN[2]}))
        after = await rf.run_set(t, (survey_command(SCAN_IF),))
        recorded[survey_command(SCAN_IF) + AFTER] = after[survey_command(SCAN_IF)]
        recorded |= await rf.run_set(t, (SCAN_DEL,))
        recorded |= await rf.run_set(t, MONITOR_WINDOW, timed=frozenset({FRAME_WINDOW}))
        recorded |= await rf.run_set(t, (DEL,))
    finally:  # nothing of the window stays on AP2, whatever failed
        await t.run(f"{SCAN_DEL} 2>/dev/null; {DEL} 2>/dev/null; true")
    own_macs = set(MAC.findall(iw_dev + str(recorded[MACADDRESS]["stdout"])))
    own_ssids = set(re.findall(r"\.ssid='([^']*)'", wireless))
    names: dict[str, str] = {}
    for cmd, entry in recorded.items():
        for field in ("stdout", "stderr"):
            if isinstance(entry.get(field), str):  # trim first: only what the parsers read is ever written
                entry[field] = rf.sanitize_air(rf.trim_air(cmd, entry[field]), own_macs, own_ssids, names)
    AIR.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(recorded)} commands to {AIR}; {len(names)} neighbour names replaced")
    assert recorded[SCAN[2]]["exit"] == 0, recorded[SCAN[2]]
    assert await _found(t) == (wireless, iw_dev), "AP2 must read exactly as found"


async def test_ap2_at_rest(ap2: ReadOnlyTransport) -> None:
    """Reads only: AP2 as the bench expects it after an air window (the parent session's "AP2 free" list).
    A fresh key login on port 22 is the SSH check."""
    names = [i.ifname for i in parse_iw_dev((await ap2.run("iw dev")).stdout)]
    assert SCAN_IF not in names and MONITOR not in names, names
    assert not any(
        i.type in ("AP", "monitor", "managed") for i in parse_iw_dev((await ap2.run("iw dev")).stdout)
    )
    uci = parse_uci_show((await ap2.run("uci -q show wireless")).stdout)
    lab = {
        k: uci.get(f"wireless.radio0.{k}") for k in ("disabled", "country", "legacy_rates", "cell_density")
    }
    assert lab == {"disabled": "1", "country": "IL", "legacy_rates": "1", "cell_density": "0"}, lab
    changes = [line for line in (await ap2.run("uci changes")).stdout.splitlines() if line.strip()]
    print(f"\nuci changes: {changes}")
    assert not any(line.startswith(("wireless.", "-wireless", "+wireless")) for line in changes), changes
    assert "owg" not in (await ap2.run("ls /tmp")).stdout.split(), "/tmp/owg is still there"
