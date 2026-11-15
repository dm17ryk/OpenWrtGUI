"""DSA bridge VLANs as LuCI's Switch/VLAN page reads them, and as netifd reports them (v1.0a3 D2, D4)."""

from __future__ import annotations

import json

import pytest

from openwrtgui.ports.bridge import (
    LiveVlan,
    PortSpec,
    bridge_devices,
    bridge_vlans,
    find_active_bridge,
    live_vlans,
    members,
    natural,
    netifd_spec,
    parse_local,
    parse_spec,
    render_spec,
    unsupported,
)

AP5 = {
    "network.cfg030f15": "device",
    "network.cfg030f15.name": "switch",
    "network.cfg030f15.type": "bridge",
    "network.cfg030f15.ports": "lan1 lan2 lan3 lan4",
    "network.cfg030f15.vlan_filtering": "1",
    "network.cfg040f15": "bridge-vlan",
    "network.cfg040f15.device": "switch",
    "network.cfg040f15.vlan": "1",
    "network.cfg040f15.ports": "lan1 lan2 lan3 lan4",
    "network.cfg050f15": "bridge-vlan",
    "network.cfg050f15.device": "switch",
    "network.cfg050f15.vlan": "10",
    "network.cfg050f15.local": "1",
    "network.cfg050f15.ports": "lan1:t lan4:t",
}
OWN = frozenset({"lan1", "lan2", "lan3", "lan4", "wan"})


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("lan1", PortSpec("lan1", tagged=False, untagged=True, pvid=True)),
        ("lan1:", PortSpec("lan1", tagged=False, untagged=True, pvid=True)),
        ("lan1:t", PortSpec("lan1", tagged=True, untagged=False, pvid=False)),
        ("lan1:u", PortSpec("lan1", tagged=False, untagged=True, pvid=False)),
        ("lan1:u*", PortSpec("lan1", tagged=False, untagged=True, pvid=True)),
        ("lan1:*", PortSpec("lan1", tagged=False, untagged=False, pvid=True)),
        ("lan1:t*", PortSpec("lan1", tagged=True, untagged=False, pvid=True)),
        ("lan1:ut", PortSpec("lan1", tagged=True, untagged=True, pvid=False)),
    ],
)
def test_entries_read_as_luci_reads_them(text: str, spec: PortSpec) -> None:
    assert parse_spec(text) == spec


@pytest.mark.parametrize("text", ["lan1:x", ":t", "lan1:t:u", ""])
def test_entries_luci_cannot_read(text: str) -> None:
    assert parse_spec(text) is None


def test_entries_as_luci_writes_them() -> None:
    assert (render_spec("lan2", "u"), render_spec("lan2", "t")) == ("lan2", "lan2:t")


@pytest.mark.parametrize(
    ("text", "reported"),
    [
        ("lan1", "lan1"),
        ("lan1:u", "lan1"),
        ("lan1:t", "lan1:t"),
        ("lan1:*", "lan1:*"),
        ("lan1:u*", "lan1:*"),
        ("lan1:t*", "lan1:t*"),
        ("bad:x", None),
    ],
)
def test_entries_as_netifd_reports_them(text: str, reported: str | None) -> None:
    """netifd bridge.c: a bare entry is untagged without the PVID flag; status prints name[:][t][*]."""
    assert netifd_spec(text) == reported


def test_local_is_on_unless_it_says_off() -> None:
    values = (None, "", "1", "on", "0", "false", "No", "OFF", "disabled")
    assert [parse_local(v) for v in values] == [True, True, True, True, False, False, False, False, False]


def test_natural_order() -> None:
    assert sorted(["lan10", "lan2", "wan", "lan1:t"], key=natural) == ["lan1:t", "lan2", "lan10", "wan"]


def test_ap5_bridge_and_vlans() -> None:
    devices, vlans = bridge_devices(AP5), bridge_vlans(AP5)
    assert [(d.name, d.ports, d.vlan_filtering) for d in devices] == [
        ("switch", ("lan1", "lan2", "lan3", "lan4"), True)
    ]
    assert [(v.section, v.vlan, v.local, v.entries) for v in vlans] == [
        ("cfg040f15", 1, True, ("lan1", "lan2", "lan3", "lan4")),
        ("cfg050f15", 10, True, ("lan1:t", "lan4:t")),
    ]
    assert members(devices[0], vlans) == ("lan1", "lan2", "lan3", "lan4")
    assert find_active_bridge(devices, vlans, OWN) == devices[0]


def test_the_active_bridge_as_luci_picks_it() -> None:
    no_filter = {
        "network.d1": "device",
        "network.d1.name": "br-lan",
        "network.d1.type": "bridge",
        "network.d1.ports": "lan1",
    }
    assert find_active_bridge(bridge_devices(no_filter), bridge_vlans(no_filter), OWN) is None
    implied = no_filter | {"network.v1": "bridge-vlan", "network.v1.device": "br-lan", "network.v1.vlan": "1"}
    # a bridge-vlan names it
    assert find_active_bridge(bridge_devices(implied), bridge_vlans(implied), OWN) is not None
    virtual = AP5 | {"network.cfg030f15.ports": "lan1 lan2 lan3 lan4 eth0.5"}
    # a VLAN device member
    assert find_active_bridge(bridge_devices(virtual), bridge_vlans(virtual), OWN) is None
    # no board.json ports
    assert find_active_bridge(bridge_devices(AP5), bridge_vlans(AP5), frozenset()) is None


def test_luci_unsupported_configs() -> None:
    bad = {
        "network.v1": "bridge-vlan",
        "network.v1.device": "switch",
        "network.v1.vlan": "5000",
        "network.v2": "bridge-vlan",
        "network.v2.device": "switch",
        "network.v2.vlan": "2",
        "network.v2.ports": "lan1:t* lan2:ut lan3:* lan4:x",
        "network.v3": "bridge-vlan",
        "network.v3.device": "switch",
        "network.v3.vlan": "3",
        "network.v3.ports": "lan1 wan",
        "network.v4": "bridge-vlan",
        "network.v4.device": "switch",
        "network.v4.vlan": "4",
        "network.v4.ports": "lan1:u",
        "network.v5": "bridge-vlan",
        "network.v5.device": "switch",
        "network.v5.vlan": "3",
    }
    assert unsupported("switch", bridge_vlans(bad)) == [
        "VLAN '5000' is not a VLAN number from 1 to 4094",
        "VLAN 2: lan1 is tagged and PVID at once (lan1:t*)",
        "VLAN 2: lan2 is tagged and untagged at once (lan2:ut)",
        "VLAN 2: lan3 has a PVID but no traffic (lan3:*)",
        "VLAN 2: 'lan4:x' is not a port entry",
        "lan1 is untagged in VLAN 3 and VLAN 4",
        "VLAN 3 is configured twice",
    ]
    assert unsupported("switch", bridge_vlans(AP5)) == []


def test_live_vlans_count_own_ports_only() -> None:
    """Review Focus 3: a Wi-Fi hotplug member and local_pvid in netifd's report are not the editor's
    business."""
    status = {
        "switch": {
            "type": "bridge",
            "bridge-members": ["lan1", "lan2", "lan3", "lan4", "wlan0"],
            "bridge-vlans": [
                {"id": 10, "local": True, "local_pvid": False, "ports": ["lan1:t", "lan4:t"]},
                {
                    "id": 1,
                    "local": True,
                    "local_pvid": True,
                    "ports": ["lan1", "lan2", "lan3", "lan4", "wlan0:*"],
                },
            ],
        },
        "lan1": {"type": "Network device", "carrier": False},
    }
    assert live_vlans(json.dumps(status), "switch", OWN) == (
        LiveVlan(1, True, frozenset({"lan1", "lan2", "lan3", "lan4"})),
        LiveVlan(10, True, frozenset({"lan1:t", "lan4:t"})),
    )
    # final review (Minor 2, re-graded Important): unreadable is never "no VLANs"
    assert live_vlans("not json", "switch", OWN) is None
    assert live_vlans(json.dumps({"lan1": {"carrier": True}}), "switch", OWN) is None  # no such bridge
    assert live_vlans(json.dumps({"switch": {"type": "bridge", "bridge-vlans": "x"}}), "switch", OWN) is None
    assert live_vlans(json.dumps({"switch": {"type": "bridge"}}), "switch", OWN) == ()  # netifd: no VLANs
    # Codex review, PR #66: a malformed `ports` is an unreadable report, not a TypeError mid-apply
    for ports in (None, {"lan1": True}, 7):
        malformed = {"switch": {"bridge-vlans": [{"id": 1, "local": True, "ports": ports}]}}
        assert live_vlans(json.dumps(malformed), "switch", OWN) is None


def test_a_port_listed_twice_in_one_vlan_is_unsupported() -> None:
    """Codex review, PR #66: `lan1 lan1:t` would collapse to one entry and an edit of another cell would drop
    the other, so the card stays read only."""
    twice = AP5 | {
        "network.cfg040f15.ports": "lan2 lan3 lan4",
        "network.cfg050f15.ports": "lan1 lan1:t lan4:t",
    }
    assert unsupported("switch", bridge_vlans(twice)) == ["VLAN 10: lan1 is listed twice (lan1:t)"]
