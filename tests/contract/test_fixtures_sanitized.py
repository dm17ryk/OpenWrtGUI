import json
import re
from collections.abc import Callable
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _texts() -> list[tuple[str, str]]:
    return [(str(p), p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.rglob("*.json"))]


def test_no_secrets_in_recordings() -> None:
    # Allowed: the masked value, the simulator's own password and the public factory default root/root.
    secret = r'"(key|password|pincode)": "(?!(<hidden>|sim-password|root)")[^"]+"'
    assert re.search(r"\b\d{15}\b", '"imei": "356938035643809"\n+CGSN: 356938035643809')
    assert re.search(r"\b\d{15}\b", "d3fb379d5d8747cb804956688523804b7116bc72") is None
    for name, text in _texts():
        decoded = json.dumps(json.loads(text))
        for blob in (text, decoded.encode().decode("unicode_escape")):
            assert re.search(secret, blob) is None, name
            # an IMEI stands alone; 15 digits inside a hex digest (a sha256) are not one
            assert re.search(r"\b\d{15}\b", blob) is None, name


def _uci_secrets(text: str) -> list[str]:
    from openwrtgui.guard.audit import SECRET_OPTIONS

    options = "|".join(SECRET_OPTIONS)
    return re.findall(rf"\.(?:{options})='(?!<hidden>')[^']*'", text)


def test_no_uci_secrets_in_recordings() -> None:
    assert _uci_secrets("wireless.default_radio0.key='lab key'\nx.y.ssid='OpenWrt'\n") == [".key='lab key'"]
    for name, text in _texts():
        recorded = json.loads(text)
        for entry in recorded.values() if isinstance(recorded, dict) else ():
            if isinstance(entry, dict):
                assert _uci_secrets(str(entry.get("stdout", ""))) == [], name


def test_ap2_recording_has_the_whole_probe_set() -> None:
    from openwrtgui.probe.commands import DESCRIBE_COMMANDS, STATUS_COMMANDS, wireless_validate

    recorded = json.loads((FIXTURES / "ap2" / "commands.json").read_text(encoding="utf-8"))
    assert set(recorded) == {*DESCRIBE_COMMANDS, *STATUS_COMMANDS, wireless_validate("radio0")}


_MAC = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}(?![:0-9a-fA-F])")
_NEIGHBOUR_SSID = re.compile(
    r"^\s*SSID: (.+)$|\b(?:Beacon|Probe Response|Probe Request|(?:Re)?Assoc Request) \((.+?)\)(?= \[|$)", re.M
)


def _trim_air() -> Callable[[str, str], str]:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "record_fixtures", FIXTURES.parents[1] / "tools" / "record_fixtures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    trim: Callable[[str, str], str] = module.trim_air
    return trim


def _air_leaks(recorded: dict[str, dict[str, object]]) -> list[tuple[str, str]]:
    """What an air recording must not hold: a neighbour's MAC or SSID (D14), or anything trim_air would cut
    (WPS names, serial numbers, mesh IDs, the payload tcpdump -v prints; review I7)."""
    trim = _trim_air()
    outputs = {
        (cmd, field): str(entry.get(field, ""))
        for cmd, entry in recorded.items()
        for field in ("stdout", "stderr")
    }
    own_text = "".join(
        outputs.get((c, "stdout"), "") for c in ("iw dev", "cat /sys/class/ieee80211/phy0/macaddress")
    )
    own_macs = {m.lower() for m in _MAC.findall(own_text)}
    own_ssids = set(re.findall(r"\.ssid='([^']*)'", outputs.get(("uci -q show wireless", "stdout"), "")))
    leaks: list[tuple[str, str]] = []
    for (cmd, field), text in outputs.items():
        if trim(cmd, text) != text:
            leaks.append((cmd, f"{field} not trimmed"))
        for mac in _MAC.findall(text):
            low = mac.lower()
            if not (low in own_macs or low.startswith("02:00:00:00:") or int(low[:2], 16) & 1):
                leaks.append((cmd, mac))
        for m in _NEIGHBOUR_SSID.finditer(text):
            ssid = (m.group(1) or m.group(2) or "").strip()
            if ssid and ssid not in own_ssids and not re.fullmatch(r"net-\d{2,}", ssid):
                leaks.append((cmd, ssid))
    return leaks


def test_air_leak_check_catches_what_the_sanitizer_must_cut() -> None:
    frames = "timeout 3 tcpdump -i owgmon0 -e -n -l -v -s 128 -c 2000"
    leaky = {
        "uci -q show wireless": {"stdout": "wireless.default_radio0.ssid='OwgTest'\n", "stderr": ""},
        frames: {
            "stdout": (
                "10:00:01.000100 1.0 Mb/s 2437 MHz 11b -70dBm signal DA:ff:ff:ff:ff:ff:ff "
                "SA:02:00:00:00:00:01 BSSID:ff:ff:ff:ff:ff:ff Probe Request (Johns-Phone-Hotspot)\n"
                "10:00:01.000200 1.0 Mb/s 2437 MHz 11b -70dBm signal BSSID:02:00:00:00:00:02 "
                "SA:02:00:00:00:00:01 DA:02:00:00:00:00:02 Data IV:1 IP 192.168.7.50 > 224.0.0.251\n"
            ),
            "stderr": "",
        },
        "iw dev owgscan0 scan passive": {
            "stdout": "BSS 02:00:00:00:00:02(on owgscan0)\n\tSSID: net-01\n\tWPS:\t * Version: 1.0\n",
            "stderr": "",
        },
    }
    found = {leak for _, leak in _air_leaks(leaky)}
    assert "Johns-Phone-Hotspot" in found
    assert "stdout not trimmed" in found
    assert len([c for c, leak in _air_leaks(leaky) if leak == "stdout not trimmed"]) == 2


def test_air_recording_names_no_neighbour() -> None:
    """v0.7 plan D14: an air recording names only the router's own networks; the rest are placeholders."""
    air = FIXTURES / "ap2" / "air.json"
    if not air.exists():
        import pytest

        pytest.skip("tests/fixtures/ap2/air.json is recorded in the AP2 window HW-1 (plan Task 3)")
    recorded: dict[str, dict[str, object]] = json.loads(air.read_text(encoding="utf-8"))
    assert _air_leaks(recorded) == []


def test_sim_routers_reference_existing_files() -> None:
    routers = json.loads((FIXTURES / "sim" / "routers.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in routers] == ["ap1", "ap2", "ap3", "new", "factory"]
    for r in routers:
        assert (FIXTURES / r["base"] / "commands.json").exists()
        if r["overlay"]:
            assert (FIXTURES / "sim" / r["overlay"]).exists()
