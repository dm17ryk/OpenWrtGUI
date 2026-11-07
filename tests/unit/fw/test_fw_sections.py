"""Traffic rules, port forwards, NAT rules and IP sets: exact previews, refusals, proof in fw4's ruleset."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.fw.compile import ModelRequest
from openwrtgui.fw.sections import ForwardRequest, IpsetRequest, NatRequest, RuleRequest

P = "uci -P /var/run/rpcd/uci-<session>"
PING = "cfg0692bd"  # Allow-Ping in the sim's (OpenWrt's default) config


def _rule(name: str = "Block-panel-ping", **kw: object) -> RuleRequest:
    base: dict[str, object] = {
        "section": None,
        "name": name,
        "src": "lan",
        "dest": None,
        "proto": "icmp",
        "src_ip": ("192.168.1.20",),
        "target": "DROP",
    }
    return RuleRequest(**(base | kw))  # type: ignore[arg-type]


async def test_add_rule_plan(env: FwEnv) -> None:
    plan = await env.fw.plan_sections("ap2", "rule", [_rule()], [])
    assert f"r1=$({P} add firewall rule)" in plan.lines
    assert f"{P} set firewall.$r1.name='Block-panel-ping'" in plan.lines
    assert f"{P} set firewall.$r1.src='lan'" in plan.lines
    assert f"{P} set firewall.$r1.proto='icmp'" in plan.lines
    assert f"{P} add_list firewall.$r1.src_ip='192.168.1.20'" in plan.lines
    assert f"{P} set firewall.$r1.target='DROP'" in plan.lines
    assert plan.rollback


async def test_rule_verified_by_fw4_comment_in_sim(env: FwEnv) -> None:
    upserts = [_rule()]
    plan = await env.fw.plan_sections("ap2", "rule", upserts, [])
    result = await env.fw.apply_sections("ap2", "rule", upserts, [], plan.digest)
    assert result.applied and result.verified, result
    assert ("rule Block-panel-ping", True) in [(c.name, c.ok) for c in result.checks]
    state = await env.fw.state("ap2")
    added = next(r for r in state.rules if r.conf.name == "Block-panel-ping")
    assert added.effect == "blocks" and added.packets == 0


async def test_disable_rule_removes_it_from_nft_in_sim(env: FwEnv) -> None:
    off = RuleRequest(
        PING,
        "Allow-Ping",
        "wan",
        None,
        "icmp",
        icmp_type=("echo-request",),
        family="ipv4",
        target="ACCEPT",
        enabled=False,
    )
    plan = await env.fw.plan_sections("ap2", "rule", [off], [])
    assert f"{P} set firewall.{PING}.enabled='0'" in plan.lines
    result = await env.fw.apply_sections("ap2", "rule", [off], [], plan.digest)
    assert result.verified, result
    assert next(c for c in result.checks if c.name == "rule Allow-Ping").detail == "gone"


async def test_delete_rule_in_sim(env: FwEnv) -> None:
    plan = await env.fw.plan_sections("ap2", "rule", [], [PING])
    assert f"{P} -q delete firewall.{PING}" in plan.lines
    result = await env.fw.apply_sections("ap2", "rule", [], [PING], plan.digest)
    assert result.verified, result
    assert "Allow-Ping" not in [r.conf.name for r in (await env.fw.state("ap2")).rules]


async def test_port_forward_plan_and_check(env: FwEnv) -> None:
    fwd = ForwardRequest(
        None, "panel-web", src_dport="8080", dest_ip="192.168.1.20", dest_port="80", proto="tcp"
    )
    plan = await env.fw.plan_sections("ap2", "redirect", [fwd], [])
    assert f"p1=$({P} add firewall redirect)" in plan.lines
    assert f"{P} set firewall.$p1.src='wan'" in plan.lines
    assert f"{P} set firewall.$p1.src_dport='8080'" in plan.lines
    assert f"{P} set firewall.$p1.dest_ip='192.168.1.20'" in plan.lines
    assert f"{P} set firewall.$p1.target='DNAT'" in plan.lines
    result = await env.fw.apply_sections("ap2", "redirect", [fwd], [], plan.digest)
    assert result.verified, result
    assert ("rule panel-web", True) in [(c.name, c.ok) for c in result.checks]


async def test_nat_and_ipset_verified_in_sim(env: FwEnv) -> None:
    nat = NatRequest(None, "snat-lab", "wan", "192.168.3.0/24", None, None, None, "SNAT", snat_ip="10.0.0.18")
    plan = await env.fw.plan_sections("ap2", "nat", [nat], [])
    assert f"n1=$({P} add firewall nat)" in plan.lines
    assert (await env.fw.apply_sections("ap2", "nat", [nat], [], plan.digest)).verified
    ipset = IpsetRequest(None, "panels", "ipv4", ("src_mac",), ("f4:12:fa:f3:57:68", "E4:5F:01:AA:BB:01"))
    plan = await env.fw.plan_sections("ap2", "ipset", [ipset], [])
    assert f"{P} add_list firewall.$s1.entry='e4:5f:01:aa:bb:01'" in plan.lines
    result = await env.fw.apply_sections("ap2", "ipset", [ipset], [], plan.digest)
    assert result.verified, result
    assert ("ipset panels", True) in [(c.name, c.ok) for c in result.checks]


async def test_snat_needs_rewrite_to(env: FwEnv) -> None:
    nat = NatRequest(None, "snat-lab", "wan", "192.168.3.0/24", None, None, None, "SNAT")
    with pytest.raises(ValueError, match="^SNAT needs a Rewrite to address$"):
        await env.fw.plan_sections("ap2", "nat", [nat], [])


async def test_ipset_entries_checked_against_match(env: FwEnv) -> None:
    ipset = IpsetRequest(None, "panels", "ipv4", ("src_mac",), ("192.168.1.1",))
    with pytest.raises(ValueError, match="^192.168.1.1 is not a MAC address$"):
        await env.fw.plan_sections("ap2", "ipset", [ipset], [])
    nets = IpsetRequest(None, "labs", "ipv4", ("dest_net",), ("10.0.0.0/8", "nope"))
    with pytest.raises(ValueError, match="^nope is not an IPv4 address or network$"):
        await env.fw.plan_sections("ap2", "ipset", [nets], [])


async def test_duplicate_names_refused(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="^There is already a rule named Allow-Ping$"):
        await env.fw.plan_sections("ap2", "rule", [_rule("Allow-Ping")], [])
    twice = ForwardRequest(None, "web", src_dport="80", dest_ip="192.168.1.20")
    with pytest.raises(ValueError, match="^There is already a port forward named web$"):
        await env.fw.plan_sections("ap2", "redirect", [twice, twice], [])


async def test_field_checks(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="^target has its own field$"):
        await env.fw.plan_sections("ap2", "rule", [_rule(others={"target": "ACCEPT"})], [])
    with pytest.raises(ValueError, match=r"^A name is 1 to 64 letters, digits, spaces, '\.', '-' or '_'$"):
        await env.fw.plan_sections("ap2", "rule", [_rule("x\n")], [])
    with pytest.raises(ValueError, match=r"^80-x is not a port or range \(e\.g\. 80 or 8000-8080\)$"):
        await env.fw.plan_sections("ap2", "rule", [_rule(proto="tcp", dest_port="80-x")], [])
    with pytest.raises(ValueError, match="^192.168.1.300 is not an IPv4 address or network$"):
        await env.fw.plan_sections("ap2", "rule", [_rule(src_ip=("192.168.1.300",))], [])
    with pytest.raises(ValueError, match="^There is no zone named guest$"):
        await env.fw.plan_sections("ap2", "rule", [_rule(src="guest")], [])


async def test_pin_not_editable_as_rule(env: FwEnv) -> None:
    req = ModelRequest({"lan.input": "REJECT"})
    plan = await env.fw.plan_model("ap2", req)
    assert (await env.fw.apply_model("ap2", req, plan.digest)).verified
    text = "^Allow SSH from this PC is kept open by the app; change it on Zones and model$"
    with pytest.raises(ValueError, match=text):
        await env.fw.plan_sections("ap2", "rule", [_rule(section="owg_pin_ssh", name="x", enabled=False)], [])
    with pytest.raises(ValueError, match=text):
        await env.fw.plan_sections("ap2", "rule", [], ["owg_pin_ssh"])
