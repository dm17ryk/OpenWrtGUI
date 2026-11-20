"""Station management against AP2's recorded hostapd (v1.2b R8, R10, R11): its ubus methods (wifi_on.json),
and the 1.2b window's recording (stations.json, 2026-11-20): the bench phone's notifications to a BSS
transition request and a beacon report request, and the neighbour list hostapd gave back."""

import json
from pathlib import Path

from openwrtgui.tools.stations import (
    HOSTAPD_LIST,
    METHODS,
    BeaconRow,
    hostapd_methods,
    neighbour_entry,
    parse_event,
)
from openwrtgui.transport.fake import load_commands

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
WINDOW = json.loads((AP2 / "stations.json").read_text(encoding="utf-8"))


def test_hostapd_has_the_five_methods_on_ap2() -> None:
    text = load_commands(AP2 / "wifi_on.json")[HOSTAPD_LIST].stdout
    assert hostapd_methods(text) == {"phy0-ap0": list(METHODS)}
    assert hostapd_methods(WINDOW["hostapd_list"]) == {"phy0-ap0": list(METHODS)}


def test_the_phone_answers_a_bss_transition_request() -> None:
    """R10: the notification is `bss-transition-response`, with `address` and an integer `status-code`."""
    events = [parse_event(line) for line in WINDOW["transition"]]
    assert events and all(e is not None for e in events)
    answers = [e for e in events if e is not None and "bss-transition" in e.type]
    assert answers and {"address", "status-code"} <= set(answers[0].fields)
    assert isinstance(answers[0].fields["status-code"], int)
    assert WINDOW["transition_detail"].startswith("The station answered the BSS transition request (status ")


def test_the_phone_sends_beacon_reports() -> None:
    """R10: `beacon-report` with `op-class`, `channel`, `rcpi`, `rsni` and `bssid`; hostapd also passes the
    station's `probe` notifications, which are no beacon rows."""
    events = [e for e in (parse_event(line) for line in WINDOW["beacon"]) if e is not None]
    reports = [e for e in events if e.type == "beacon-report"]
    assert reports and {"op-class", "channel", "rcpi", "rsni", "bssid"} <= set(reports[0].fields)
    rows = [BeaconRow.of(e) for e in reports]
    assert all(r.channel == 11 and r.rcpi_dbm is not None and r.bssid for r in rows)
    assert any(e.type == "probe" for e in events)
    assert WINDOW["beacon_detail"] == f"The station sent {len(reports)} beacon reports."


def test_the_neighbour_list_hostapd_gave_back() -> None:
    listed = json.loads(WINDOW["rrm_nr_list_after_set"])["list"]
    entries = [neighbour_entry(value, "AP2 · OwgTest") for value in listed]
    assert len(entries) == 1 and entries[0] is not None and entries[0].ssid == "OwgTest"
