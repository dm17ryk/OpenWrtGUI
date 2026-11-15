"""The VLAN editor's rules (v1.0a3 D2, D3 layer 1) and the uci ops: only bridge-vlan sections are written."""

from __future__ import annotations

from dataclasses import replace

import pytest

from openwrtgui.ports.bridge import BridgePortView, BridgeState, BridgeVlanView, LiveVlan
from openwrtgui.ports.bridge_rules import BridgeVlanRequest, bridge_change
from openwrtgui.uci import UciOp

NAME = "AP5 · DSA image"
VLAN1 = BridgeVlanView(
    "cfg040f15",
    1,
    True,
    dict.fromkeys(("lan1", "lan2", "lan3", "lan4"), "u"),
    {p: p for p in ("lan1", "lan2", "lan3", "lan4")},
    ("lan",),
    True,
)
VLAN10 = BridgeVlanView(
    "cfg050f15", 10, True, {"lan1": "t", "lan4": "t"}, {"lan1": "lan1:t", "lan4": "lan4:t"}, ("iot",), False
)
AP5 = BridgeState(
    router_id="ap5",
    bridge="switch",
    editable=True,
    blocker=None,
    issues=(),
    ports=(
        BridgePortView("lan1", False, False),
        BridgePortView("lan2", False, False),
        BridgePortView("lan3", True, True),
        BridgePortView("lan4", False, False),
    ),
    vlans=(VLAN1, VLAN10),
    own_interface="lan",
    own_vlan=1,
)
ALL = {"lan1": "u", "lan2": "u", "lan3": "u", "lan4": "u"}


def _req(
    vlan: int, members: dict[str, str], section: str | None = None, local: bool = True
) -> BridgeVlanRequest:
    return BridgeVlanRequest(section, vlan, members, local)  # type: ignore[arg-type]


def test_a_new_vlan_tagged_on_a_port() -> None:
    change = bridge_change(AP5, [_req(20, {"lan2": "t"})], [], NAME)
    assert change.ops == (
        UciOp("add", "network.$b1", "bridge-vlan"),
        UciOp("set", "network.$b1.device", "switch"),
        UciOp("set", "network.$b1.vlan", "20"),
        UciOp("set", "network.$b1.local", "1"),
        UciOp("add_list", "network.$b1.ports", "lan2:t"),
    )
    assert change.want == (
        LiveVlan(1, True, frozenset({"lan1", "lan2", "lan3", "lan4"})),
        LiveVlan(10, True, frozenset({"lan1:t", "lan4:t"})),
        LiveVlan(20, True, frozenset({"lan2:t"})),
    )


def test_a_port_moved_to_a_new_vlan() -> None:
    no_lan4 = {k: v for k, v in ALL.items() if k != "lan4"}
    change = bridge_change(AP5, [_req(1, no_lan4, "cfg040f15"), _req(30, {"lan4": "u"})], [], NAME)
    assert change.ops[:4] == (
        UciOp("delete", "network.cfg040f15.ports"),
        UciOp("add_list", "network.cfg040f15.ports", "lan1"),
        UciOp("add_list", "network.cfg040f15.ports", "lan2"),
        UciOp("add_list", "network.cfg040f15.ports", "lan3"),
    )
    assert UciOp("add_list", "network.$b2.ports", "lan4") in change.ops
    own = "VLAN 1 carries lan, this app's connection; the change applies with a 60 s rollback."
    assert own in change.warnings


def test_a_port_untagged_twice_is_refused() -> None:
    with pytest.raises(
        ValueError, match="lan2 is untagged in VLAN 1 and VLAN 20; a port is untagged in one VLAN at most."
    ):
        bridge_change(AP5, [_req(20, {"lan2": "u"})], [], NAME)


def test_an_unchanged_cell_keeps_its_entry_as_written() -> None:
    """Review Focus 2: `lan2:u*`-style entries survive an edit of another cell in the VLAN."""
    kept = replace(VLAN1, entries={"lan1": "lan1", "lan2": "lan2:u*", "lan3": "lan3:u*", "lan4": "lan4"})
    state = replace(AP5, vlans=(kept, VLAN10))
    change = bridge_change(state, [_req(1, {"lan2": "u", "lan3": "u", "lan4": "u"}, "cfg040f15")], [], NAME)
    assert [op.value for op in change.ops if op.op == "add_list"] == ["lan2:u*", "lan3:u*", "lan4"]
    assert LiveVlan(1, True, frozenset({"lan2:*", "lan3:*", "lan4"})) in change.want


def test_no_change_writes_nothing() -> None:
    reordered = replace(VLAN10, entries={"lan4": "lan4:t", "lan1": "lan1:t"})
    state = replace(AP5, vlans=(VLAN1, reordered))
    assert bridge_change(state, [_req(10, {"lan1": "t", "lan4": "t"}, "cfg050f15")], [], NAME).ops == ()


def test_local_switch_and_its_warning() -> None:
    change = bridge_change(AP5, [_req(10, {"lan1": "t", "lan4": "t"}, "cfg050f15", local=False)], [], NAME)
    assert change.ops == (UciOp("set", "network.cfg050f15.local", "0"),)
    warning = "VLAN 10 carries iot: with local off the router leaves VLAN 10, so iot gets no traffic."
    assert warning in change.warnings
    with pytest.raises(ValueError, match="VLAN 1 carries lan, this app's connection: the router stays in it"):
        bridge_change(AP5, [_req(1, ALL, "cfg040f15", local=False)], [], NAME)


@pytest.mark.parametrize(
    ("upserts", "deletes", "message"),
    [
        (
            [_req(2, {}, "cfg050f15")],
            [],
            "VLAN 10 keeps its number here: add VLAN 2 and remove VLAN 10 instead.",
        ),
        ([_req(4095, {})], [], "VLAN numbers are 1 to 4094"),
        ([_req(10, {})], [], "There is already a VLAN 10"),
        ([_req(20, {}), _req(20, {})], [], "There is already a VLAN 20"),
        ([_req(20, {"lan9": "t"})], [], "lan9 is not a port of switch"),
        ([_req(20, {}, "cfg999999")], [], "There is no VLAN cfg999999"),
        ([], ["cfg050f15"], r"VLAN 10 carries iot \(switch\.10\)\. Move iot to another device first\."),
        ([], ["cfg040f15"], r"VLAN 1 carries lan \(switch\.1\)\. Move lan to another device first\."),
    ],
)
def test_refusals(upserts: list[BridgeVlanRequest], deletes: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        bridge_change(AP5, upserts, deletes, NAME)


def test_a_vlan_nothing_uses_can_go() -> None:
    spare = BridgeVlanView("cfg060f15", 30, True, {"lan2": "t"}, {"lan2": "lan2:t"}, (), False)
    change = bridge_change(replace(AP5, vlans=(VLAN1, VLAN10, spare)), [], ["cfg060f15"], NAME)
    assert change.ops == (UciOp("delete", "network.cfg060f15"),)
    assert all(v.vlan != 30 for v in change.want)


def test_the_management_path_rule() -> None:
    """D3 layer 1: one port that may carry the SSH keeps its own-VLAN entry as written."""
    refusal = (
        r"lan3 may carry this app's SSH to AP5 · DSA image \(the ports with a link in VLAN 1, which carries "
        r"lan\): one of them keeps its VLAN 1 membership as it is\."
    )
    with pytest.raises(ValueError, match=refusal):
        bridge_change(AP5, [_req(1, {"lan1": "u", "lan2": "u", "lan4": "u"}, "cfg040f15")], [], NAME)
    with pytest.raises(ValueError, match=refusal):
        bridge_change(AP5, [_req(1, ALL | {"lan3": "t"}, "cfg040f15")], [], NAME)
    two = replace(AP5, ports=(BridgePortView("lan1", True, True), *AP5.ports[1:]))
    moved = bridge_change(two, [_req(1, {"lan1": "u", "lan2": "u", "lan4": "u"}, "cfg040f15")], [], NAME)
    assert moved.ops  # allowed: lan1 keeps its entry; the rollback catches a cut (Task 6)
    elsewhere = replace(AP5, own_vlan=None, own_interface="wan", vlans=(replace(VLAN1, own=False), VLAN10))
    assert bridge_change(elsewhere, [_req(1, ALL | {"lan3": "t"}, "cfg040f15")], [], NAME).ops


def test_a_read_only_card_refuses_every_change() -> None:
    blocked = replace(AP5, editable=False, blocker="lan uses switch itself")
    with pytest.raises(ValueError, match="lan uses switch itself"):
        bridge_change(blocked, [_req(20, {})], [], NAME)
    with pytest.raises(ValueError, match="This router has no bridge with VLAN filtering"):
        bridge_change(replace(AP5, bridge=None, editable=False), [_req(20, {})], [], NAME)


def test_an_empty_vlan_warns() -> None:
    change = bridge_change(AP5, [_req(20, {})], [], NAME)
    assert "VLAN 20 has no ports." in change.warnings
    assert not any(op.op == "add_list" for op in change.ops)
