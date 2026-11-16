"""The VLAN editor on ap5 (v1.0a3): previews, applies with the rollback, and a cut that comes back by
itself."""

from __future__ import annotations

import json

import pytest
from bridgeenv import BridgeEnv

from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.ports.bridge import LiveVlan
from openwrtgui.ports.bridge_rules import BridgeVlanRequest
from openwrtgui.ports.bridge_service import BridgeVlanService
from openwrtgui.transport.base import CommandResult
from openwrtgui.wifi.service import PreviewChanged

P = "uci -P /var/run/rpcd/uci-<session>"
ALL: dict[str, str] = {"lan1": "u", "lan2": "u", "lan3": "u", "lan4": "u"}


def _svc(bridge: BridgeEnv) -> BridgeVlanService:
    assert bridge.service is not None
    return bridge.service


def _req(section: str | None, vlan: int, members: dict[str, str]) -> BridgeVlanRequest:
    return BridgeVlanRequest(section, vlan, members)  # type: ignore[arg-type]


async def _sections(bridge: BridgeEnv) -> dict[int, str]:
    return {v.vlan: v.section for v in (await _svc(bridge).state("ap5")).vlans}


async def test_a_new_vlan_previewed_exactly(bridge: BridgeEnv) -> None:
    plan = await _svc(bridge).plan("ap5", [_req(None, 20, {"lan2": "t"})], [])
    assert plan.rollback and plan.config == "network"
    assert f"b1=$({P} add network bridge-vlan)" in plan.lines
    assert f"{P} set network.$b1.device='switch'" in plan.lines
    assert f"{P} add_list network.$b1.ports='lan2:t'" in plan.lines
    rollback = "Applies with a 60 s rollback: if the app cannot reach AP5 · DSA image"
    assert plan.warnings[-1].startswith(rollback)


async def test_a_new_vlan_applied_and_proven_by_netifd(bridge: BridgeEnv) -> None:
    result = await _svc(bridge).apply("ap5", [_req(None, 20, {"lan2": "t"})], [])
    assert (result.applied, result.verified) == (True, True), result
    assert [c.name for c in result.checks] == ["reconnected", "confirmed", "bridge"]
    vlans = {v.vlan: v.members for v in (await _svc(bridge).state("ap5")).vlans}
    assert vlans[20] == {"lan2": "t"}


async def test_a_change_that_moves_the_pcs_port_rolls_back_by_itself(bridge: BridgeEnv) -> None:
    """Review Focus 1, D3 layer 2: two linked ports pass the management-path rule, so the app cannot tell the
    PC's port; moving lan3 out of VLAN 1 cuts the app off, and rpcd restores the previous settings at 60 s."""
    sections = await _sections(bridge)
    bridge.sim().dsa_links.add("lan1")
    upserts = [
        _req(sections[1], 1, {"lan1": "u", "lan2": "u", "lan4": "u"}),
        _req(None, 30, {"lan3": "u"}),
    ]
    result = await _svc(bridge).apply("ap5", upserts, [])
    assert not result.applied and not result.verified
    assert {c.name: c.ok for c in result.checks} == {"reconnected": False, "restored": True}
    assert result.error == (
        "Not applied: AP5 · DSA image did not answer at 192.168.1.7 within 40 s. "
        "The router restores its previous network settings 60 s after the change."
    )
    vlan1 = next(v for v in (await _svc(bridge).state("ap5")).vlans if v.vlan == 1)
    assert "lan3" in vlan1.members
    assert not any(e.command.startswith("ubus call uci confirm") for e in bridge.audit.query())


async def test_the_pcs_only_port_is_refused_before_the_preview(bridge: BridgeEnv) -> None:
    sections = await _sections(bridge)
    with pytest.raises(ValueError, match="lan3 may carry this app's SSH to AP5 · DSA image"):
        await _svc(bridge).plan("ap5", [_req(sections[1], 1, ALL | {"lan3": "t"})], [])
    assert not any("uci apply" in e.command for e in bridge.audit.query())


async def test_a_pending_rollback_of_another_client_refuses_the_change(bridge: BridgeEnv) -> None:
    """Review Focus 5: rpcd refuses a second rollback apply; nothing is staged or changed."""
    await _svc(bridge).state("ap5")
    bridge.sim().pending_rollback(30)
    result = await _svc(bridge).apply("ap5", [_req(None, 20, {"lan2": "t"})], [])
    assert not result.applied
    assert result.error == "The router refused the change: Command failed: Permission denied"
    assert 20 not in {v.vlan for v in (await _svc(bridge).state("ap5")).vlans}
    assert any(e.command.startswith("ubus call session destroy") for e in bridge.audit.query())  # #68


async def test_nothing_to_apply_and_bench_guard(bridge: BridgeEnv) -> None:
    sections = await _sections(bridge)
    with pytest.raises(ValueError, match="Nothing to apply"):
        await _svc(bridge).plan("ap5", [_req(sections[10], 10, {"lan1": "t", "lan4": "t"})], [])
    bridge.go_live()
    with pytest.raises(GuardLocked):
        await _svc(bridge).apply("ap5", [_req(None, 20, {"lan2": "t"})], [])


class _FailingRead:
    """A connection whose `network.device status` read fails (ubus down, a timeout)."""

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return CommandResult(command, "", "Command failed: Not found", 4)


async def test_an_unreadable_report_never_proves_a_change_that_leaves_no_vlans(bridge: BridgeEnv) -> None:
    """Final review (Minor 2, re-graded Important): D4, nothing is kept unseen. A change whose wanted state is
    "no VLANs" must not be confirmed because the report could not be read."""
    verify = _svc(bridge)._verify("switch", frozenset({"lan1", "lan2"}), ())
    checks = await verify(_FailingRead())  # type: ignore[arg-type]
    assert [(c.name, c.ok) for c in checks] == [("bridge", False)]
    assert "could not be read" in checks[0].detail


async def test_a_digest_that_differs_sends_nothing(bridge: BridgeEnv) -> None:
    with pytest.raises(PreviewChanged):
        await _svc(bridge).apply("ap5", [_req(None, 20, {"lan2": "t"})], [], "0" * 16)


async def test_a_section_changed_twice_is_refused_before_the_preview(bridge: BridgeEnv) -> None:
    """v1.0a3 minor (#66), v1.0b2 D12: the API can send it, the card cannot."""
    s10 = (await _sections(bridge))[10]
    with pytest.raises(ValueError, match=f"^{s10} is changed twice in one apply$"):
        await _svc(bridge).plan("ap5", [_req(s10, 10, {"lan1": "t"})], [s10])
    with pytest.raises(ValueError, match=f"^{s10} is changed twice in one apply$"):
        await _svc(bridge).plan("ap5", [], [s10, s10])


class _WithWifi:
    """netifd's report with a Wi-Fi interface in VLAN 1: wireless interfaces join the bridge, not the
    editor."""

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        vlan = {"id": 1, "local": True, "ports": ["lan1", "lan2", "phy0-ap0"]}
        return CommandResult(command, json.dumps({"switch": {"bridge-vlans": [vlan]}}), "", 0)


async def test_a_wifi_interface_in_a_bridge_vlan_is_left_out_of_the_proof(bridge: BridgeEnv) -> None:
    """v1.0a3 test gap (#68)."""
    want = (LiveVlan(1, True, frozenset({"lan1", "lan2"})),)
    verify = _svc(bridge)._verify("switch", frozenset({"lan1", "lan2"}), want)
    checks = await verify(_WithWifi())  # type: ignore[arg-type]
    assert [(c.name, c.ok) for c in checks] == [("bridge", True)]
