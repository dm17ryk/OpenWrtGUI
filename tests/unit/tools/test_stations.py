"""Station management (v1.2b R8-R10): hostapd's ubus methods, the three requests, and their answers."""

from __future__ import annotations

import json

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.tools.stations import (
    METHODS,
    BeaconRow,
    HostapdEvent,
    beacon_request_command,
    hostapd_methods,
    listen_command,
    neighbour_entry,
    neighbours_set_command,
    op_class,
    parse_event,
    transition_command,
)

MAC = "02:00:00:00:00:30"
OWN = ["02:00:00:00:00:01", "OwgTest", "0200000000010000000000000000000000"]
UBUS_LIST = (
    "'hostapd.phy0-ap0' @3456734a\n"
    '\t"reload":{}\n'
    '\t"del_client":{"addr":"String"}\n'
    '\t"rrm_nr_get_own":{}\n'
    '\t"rrm_nr_list":{}\n'
    '\t"rrm_nr_set":{"list":"Array"}\n'
    '\t"rrm_beacon_req":{"addr":"String"}\n'
    '\t"bss_transition_request":{"addr":"String"}\n'
    "'hostapd.phy0-ap1' @3456734b\n"
    '\t"reload":{}\n'
)


def test_hostapd_methods() -> None:
    assert hostapd_methods(UBUS_LIST) == {"phy0-ap0": list(METHODS), "phy0-ap1": []}


@pytest.mark.parametrize(("channel", "klass"), [(1, 81), (11, 81), (13, 81), (14, 82), (36, 115), (52, 118)])
def test_op_class(channel: int, klass: int) -> None:
    assert op_class(channel) == klass


def test_op_class_of_other_bands() -> None:
    assert (op_class(100), op_class(144), op_class(149), op_class(177)) == (121, 121, 125, 125)
    with pytest.raises(ValueError):
        op_class(200)


def test_transition_command() -> None:
    command = transition_command("phy0-ap0", MAC, OWN[2])
    args = {
        "abridged": True,
        "addr": MAC,
        "disassociation_imminent": False,
        "disassociation_timer": 0,
        "neighbors": [OWN[2]],
        "validity_period": 100,
    }
    assert command == "ubus call hostapd.phy0-ap0 bss_transition_request " + _quoted(args)
    assert not is_read_only_command(command)


def test_beacon_request_command() -> None:
    command = beacon_request_command("phy0-ap0", MAC, 11)
    args = {
        "addr": MAC,
        "bssid": "ff:ff:ff:ff:ff:ff",
        "channel": 11,
        "duration": 100,
        "mode": 1,
        "op_class": 81,
    }
    assert command == "ubus call hostapd.phy0-ap0 rrm_beacon_req " + _quoted(args)
    assert not is_read_only_command(command)


def test_neighbours_set_command() -> None:
    command = neighbours_set_command("phy0-ap0", [OWN])
    assert command == "ubus call hostapd.phy0-ap0 rrm_nr_set " + _quoted({"list": [OWN]})
    assert not is_read_only_command(command)
    assert neighbours_set_command("phy0-ap0", []).endswith(_quoted({"list": []}))


def test_listen_command() -> None:
    assert listen_command("phy0-ap0") == "timeout -s KILL 12 ubus subscribe hostapd.phy0-ap0"
    assert not is_read_only_command(listen_command("phy0-ap0"))


def test_bad_ifname_or_mac_never_reach_a_command() -> None:
    with pytest.raises(ValueError):
        transition_command("phy0-ap0;reboot", MAC, OWN[2])
    with pytest.raises(ValueError):
        beacon_request_command("phy0-ap0", "x'; reboot", 11)


def test_neighbour_entries_are_checked() -> None:
    good = neighbour_entry(OWN, "AP2 · OwgTest")
    assert good is not None and (good.bssid, good.ssid, good.nr) == (OWN[0], OWN[1], OWN[2])
    assert neighbour_entry(["02:00:00:00:00:0G", "x", "00"], "s") is None
    assert neighbour_entry([OWN[0], "", OWN[2]], "s") is None
    assert neighbour_entry([OWN[0], "a" * 33, OWN[2]], "s") is None
    assert neighbour_entry([OWN[0], "x", "0"], "s") is None  # odd length
    assert neighbour_entry([OWN[0], "x", "zz"], "s") is None
    assert neighbour_entry("not a list", "s") is None


def test_events() -> None:
    beacon = {"beacon-report": {"address": MAC, "op-class": 81, "channel": 11, "rcpi": 120, "rsni": 40}}
    event = parse_event(json.dumps(beacon))
    assert event == HostapdEvent(
        type="beacon-report", fields={"address": MAC, "op-class": 81, "channel": 11, "rcpi": 120, "rsni": 40}
    )
    assert parse_event("not json") is None and parse_event("[1]") is None
    assert BeaconRow.of(event) == BeaconRow(bssid=None, channel=11, rcpi_dbm=-50.0, rsni=40)


def _quoted(args: dict[str, object]) -> str:
    return "'" + json.dumps(args, separators=(",", ":"), sort_keys=True) + "'"
