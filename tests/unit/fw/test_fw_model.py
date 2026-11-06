"""The filtering model per zone and direction, and the pins that keep the app's own path open."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.fw.compile import ModelRequest

P = "uci -P /var/run/rpcd/uci-<session>"
LAN = "firewall.cfg02dc81"  # the sim's lan zone section (OpenWrt's default config)


async def test_block_all_on_own_zone_adds_ssh_pin(env: FwEnv) -> None:
    plan = await env.fw.plan_model("ap2", ModelRequest({"lan.input": "REJECT"}))
    assert f"{P} set {LAN}.input='REJECT'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh='rule'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.name='Allow SSH from this PC'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.src='lan'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.src_ip='192.168.1.10'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.proto='tcp'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.dest_port='22'" in plan.lines
    assert f"{P} set firewall.owg_pin_ssh.target='ACCEPT'" in plan.lines
    assert (
        'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"<session>"}\'' in plan.lines
    )
    assert plan.rollback and plan.config == "firewall"
    assert not any("owg_pin_dhcpdns" in line for line in plan.lines)


async def test_dhcp_pin_only_where_router_serves_dhcp(env: FwEnv) -> None:
    plan = await env.fw.plan_model("ap1", ModelRequest({"lan.input": "DROP"}))
    assert f"{P} set firewall.owg_pin_dhcpdns.dest_port='53 67 68'" in plan.lines
    assert f"{P} set firewall.owg_pin_dhcpdns.proto='udp tcp'" in plan.lines


async def test_pin_removed_warns(env: FwEnv) -> None:
    plan = await env.fw.plan_model("ap2", ModelRequest({"lan.input": "REJECT"}, frozenset({"ssh"})))
    assert not any("owg_pin_ssh" in line for line in plan.lines)
    assert (
        "Without this rule the app loses AP2 · office as soon as the change applies. "
        "The 60 s rollback then restores the old firewall by itself." in plan.warnings
    )


async def test_flag_summary_when_rules_stop_doing_anything(env: FwEnv) -> None:
    plan = await env.fw.plan_model("ap2", ModelRequest({"wan.input": "ACCEPT"}))
    assert (
        "3 rules no longer do anything in this model. They stay in the config, so switching back restores "
        "them; delete them here if you no longer need them." in plan.warnings
    )


async def test_unknown_zone_or_direction_refused(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="There is no zone named guest"):
        await env.fw.plan_model("ap2", ModelRequest({"guest.input": "ACCEPT"}))
    with pytest.raises(ValueError, match="sideways is not input, forward or output"):
        await env.fw.plan_model("ap2", ModelRequest({"lan.sideways": "ACCEPT"}))


async def test_unpinned_block_all_rolls_back_in_sim(env: FwEnv) -> None:
    req = ModelRequest({"lan.input": "DROP"}, frozenset({"ssh"}))
    plan = await env.fw.plan_model("ap2", req)
    result = await env.fw.apply_model("ap2", req, plan.digest)
    assert not result.applied and not result.verified
    checks = {c.name: c.ok for c in result.checks}
    assert checks["reconnected"] is False and checks["restored"] is True
    assert result.error is not None
    assert result.error.endswith("The router restores its previous firewall settings 60 s after the change.")
    assert next(z for z in (await env.fw.state("ap2")).conf.zones if z.name == "lan").input == "ACCEPT"


async def test_pinned_block_all_verified_in_sim(env: FwEnv) -> None:
    req = ModelRequest({"lan.input": "REJECT"})
    plan = await env.fw.plan_model("ap2", req)
    result = await env.fw.apply_model("ap2", req, plan.digest)
    assert result.applied and result.verified, result
    names = [c.name for c in result.checks]
    assert {"reconnected", "confirmed", "saved", "zone lan input", "rule Allow SSH from this PC"} <= set(
        names
    )
    state = await env.fw.state("ap2")
    assert next(p for p in state.pins if p.id == "ssh").present
