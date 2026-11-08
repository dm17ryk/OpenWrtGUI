import json
import re
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


def test_sim_routers_reference_existing_files() -> None:
    routers = json.loads((FIXTURES / "sim" / "routers.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in routers] == ["ap1", "ap2", "ap3", "new", "factory"]
    for r in routers:
        assert (FIXTURES / r["base"] / "commands.json").exists()
        if r["overlay"]:
            assert (FIXTURES / "sim" / r["overlay"]).exists()
