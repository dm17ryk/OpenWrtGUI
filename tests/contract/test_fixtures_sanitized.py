import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _texts() -> list[tuple[str, str]]:
    return [(str(p), p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.rglob("*.json"))]


def test_no_secrets_in_recordings() -> None:
    # Allowed: the masked value, the simulator's own password and the public factory default root/root.
    secret = r'"(key|password|pincode)": "(?!(<hidden>|sim-password|root)")[^"]+"'
    for name, text in _texts():
        decoded = json.dumps(json.loads(text))
        for blob in (text, decoded.encode().decode("unicode_escape")):
            assert re.search(secret, blob) is None, name
            assert re.search(r"\d{15}", blob) is None, name


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
