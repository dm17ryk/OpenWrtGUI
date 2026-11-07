"""The firewall as the screen shows it: zones, rules with their effect in the model, pins, owners."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fwenv import FwEnv

from openwrtgui.fw.compile import ModelRequest
from openwrtgui.fw.parse import firewall_conf
from openwrtgui.fw.state import rule_effect
from openwrtgui.uci import parse_uci_show

CONF = """firewall.d=defaults
firewall.lan=zone
firewall.lan.name='lan'
firewall.lan.network='lan'
firewall.lan.input='REJECT'
firewall.lan.output='ACCEPT'
firewall.lan.forward='ACCEPT'
firewall.wan=zone
firewall.wan.name='wan'
firewall.wan.network='wan'
firewall.wan.input='ACCEPT'
firewall.wan.output='ACCEPT'
firewall.wan.forward='REJECT'
firewall.f=forwarding
firewall.f.src='lan'
firewall.f.dest='wan'
firewall.ping=rule
firewall.ping.name='Allow-Ping'
firewall.ping.src='wan'
firewall.ping.proto='icmp'
firewall.ping.target='ACCEPT'
firewall.drop=rule
firewall.drop.name='Drop-panel'
firewall.drop.src='lan'
firewall.drop.target='DROP'
firewall.out=rule
firewall.out.name='To-wan'
firewall.out.src='lan'
firewall.out.dest='wan'
firewall.out.target='ACCEPT'
firewall.block=rule
firewall.block.name='Block-to-wan'
firewall.block.src='lan'
firewall.block.dest='wan'
firewall.block.target='DROP'
firewall.any=rule
firewall.any.name='Any-zone'
firewall.any.src='*'
firewall.any.target='DROP'
"""


def test_rule_effect_flags() -> None:
    conf = firewall_conf(parse_uci_show(CONF))
    effect = {r.name: rule_effect(r, conf) for r in conf.rules}
    assert (effect["Allow-Ping"].direction, effect["Allow-Ping"].zone) == ("input", "wan")
    assert effect["Allow-Ping"].effect == "no-effect-allow"  # wan input already allows
    assert effect["Drop-panel"].effect == "no-effect-block"  # lan input already blocks
    assert effect["To-wan"].effect == "no-effect-allow"  # the lan→wan forwarding allows it
    assert effect["Block-to-wan"].effect == "blocks"
    assert effect["Any-zone"].effect == "other"
    assert effect["Drop-panel"].target_class == "block"


async def test_ap2_state(env: FwEnv) -> None:
    state = await env.fw.state("ap2")
    assert state.available and state.reason is None
    assert state.own_zone == "lan" and state.pc_ip == "192.168.1.10" and state.ssh_port == 22
    wan = next(z for z in state.conf.zones if z.name == "wan")
    assert wan.input == "REJECT"
    ping = next(r for r in state.rules if r.conf.name == "Allow-Ping")
    assert ping.effect == "allows" and ping.packets == 0
    assert [(o.key, o.owner) for o in state.objects] == [("inet fw4", "fw4")]
    assert [(p.id, p.present) for p in state.pins] == [("ssh", False)]  # AP2 serves no DHCP


async def test_ap1_objects_and_owners(env: FwEnv) -> None:
    state = await env.fw.state("ap1")
    owners = {o.key: (o.owner, o.writer) for o in state.objects}
    assert owners == {
        "inet fw4": ("fw4", None),
        "inet fw4 chain BENCHSIPGUARD": ("known", "dima_night"),
        "bridge voipdscp": ("known", "voip_chain"),
        "ip lab_scratch": ("unknown", None),
    }
    sip = next(o for o in state.objects if o.chain == "BENCHSIPGUARD")
    assert sip.depends == (
        "dima_night expects BENCHSIPGUARD. Without it, SIP from the panels leaves the bench during soak runs."
    )
    assert sip.rules == 2
    assert [p.id for p in state.pins] == ["ssh", "dhcpdns"]  # AP1 serves DHCP on lan


async def test_not_fw4_router_unavailable(env: FwEnv) -> None:
    await env.fw.state("ap2")
    desc = env.descriptions["ap2"]
    env.descriptions["ap2"] = replace(desc, features={**(desc.features or {}), "firewall4": False})
    state = await env.fw.state("ap2")
    assert not state.available
    assert state.reason == "This router does not run fw4 (firewall4); its firewall is not managed here."
    with pytest.raises(ValueError, match=r"does not run fw4"):
        await env.fw.plan_model("ap2", ModelRequest({"lan.input": "REJECT"}))
