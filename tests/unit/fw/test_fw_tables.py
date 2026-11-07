"""Other nftables tables: locked unless the change says it overrides, edited as nft's own text in one
transaction, rolled back by a router-side timer, kept at runtime or saved as an fw4 include."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.fw.nft import render_table, table_texts
from openwrtgui.fw.tables import ChainEdit, TableRequest
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.simfw import SimFirewall
from openwrtgui.transport.base import CommandResult

VOIP = "bridge voipdscp"
SIP = "inet fw4 chain BENCHSIPGUARD"
VOIP_RULES = (
    ("post", "udp dport 5004 ip dscp set ef counter"),
    ("post", "udp dport { 5060, 5061 } ip dscp set ef counter"),
)


def _heredoc(head: str, lines: tuple[str, ...]) -> str:
    """The lines of a preview from `<head> <<'OWG'` to `OWG`."""
    start = next(i for i, line in enumerate(lines) if line == f"{head} <<'OWG'")
    end = lines.index("OWG", start)
    return "\n".join(lines[start + 1 : end])


async def test_locked_object_refused_without_override(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="^bridge voipdscp belongs to voip_chain; unlock it first.$"):
        await env.fw.plan_table("ap1", TableRequest(VOIP, "edit", rules=VOIP_RULES[:1]))
    with pytest.raises(ValueError, match="^ip lab_scratch belongs to an unknown writer; unlock it first.$"):
        await env.fw.plan_table("ap1", TableRequest("ip lab_scratch", "delete"))
    with pytest.raises(ValueError, match="^inet fw4 is fw4's own table: change it on the other tabs.$"):
        await env.fw.plan_table("ap1", TableRequest("inet fw4", "delete", override=True))


async def test_benchfault_is_left_to_the_faults_screen(env: FwEnv) -> None:
    # an edit here would leave the fault records and their timers pointing at chains that changed
    assert (await (await env.sim("ap1")).run("nft add table netdev benchfault")).ok
    text = "^netdev benchfault holds the faults this app armed: clear them on the Faults screen.$"
    with pytest.raises(ValueError, match=text):
        await env.fw.plan_table("ap1", TableRequest("netdev benchfault", "delete"))
    with pytest.raises(ValueError, match=text):
        await env.fw.plan_table("ap1", TableRequest("netdev benchfault", "edit", override=True))


async def test_include_that_fails_to_save_is_reported(env: FwEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    real = SimFirewall._heredoc

    def no_write(self: SimFirewall, command: str, head: str, text: str) -> CommandResult | None:
        if head.startswith("cat > /etc/owg/"):
            return CommandResult(command, "", "sh: can't create /etc/owg/nft: Read-only file system\n", 1)
        return real(self, command, head, text)

    monkeypatch.setattr(SimFirewall, "_heredoc", no_write)
    req = TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES, keep="include")
    plan = await env.fw.plan_table("ap1", req)
    result = await env.fw.apply_table("ap1", req, plan.digest)
    assert result.applied and not result.verified
    assert result.error is not None and result.error.startswith(
        "Applied at runtime; saving it as an fw4 include failed: "
    ), result


async def test_unchanged_table_round_trips(env: FwEnv) -> None:
    plan = await env.fw.plan_table("ap1", TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES))
    listed = table_texts(await env.fw.ruleset_text("ap1"))[("bridge", "voipdscp")]
    assert _heredoc("nft -f /dev/stdin", plan.lines) == "delete table bridge voipdscp\n" + render_table(
        listed
    ).rstrip("\n")


async def test_edit_voipdscp_plan_in_sim(env: FwEnv) -> None:
    req = TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES[:1])
    plan = await env.fw.plan_table("ap1", req)
    lines = plan.lines
    assert lines[:2] == ("set -e", "nft list table bridge voipdscp > /tmp/owg/rb-<rollback>.nft")
    assert lines[2].startswith(
        "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/rb-<rollback>.pid"
    )
    assert "nft delete table bridge voipdscp 2>/dev/null; nft -f /tmp/owg/rb-<rollback>.nft" in lines[2]
    assert "nft -c -f /dev/stdin <<'OWG'" in lines and "nft -f /dev/stdin <<'OWG'" in lines
    assert lines[-1].startswith("start-stop-daemon -K -q -p /tmp/owg/rb-<rollback>.pid")
    assert any("belongs to voip_chain" in w for w in plan.warnings)
    result = await env.fw.apply_table("ap1", req, plan.digest)
    assert result.applied and result.verified, result
    assert ("table bridge voipdscp", True) in [(c.name, c.ok) for c in result.checks]
    after = table_texts(await env.fw.ruleset_text("ap1"))[("bridge", "voipdscp")]
    assert after.chains[0].rules == ("udp dport 5004 ip dscp set ef counter",)
    assert "override bridge voipdscp (owner voip_chain)" in env.audit_lines()


async def test_fw4_chain_edit_uses_flush_chain(env: FwEnv) -> None:
    rule = 'oifname { "eth0.2", "wwan0" } udp dport { 5060, 5061 } counter reject'
    plan = await env.fw.plan_table(
        "ap1", TableRequest(SIP, "edit", override=True, rules=(("BENCHSIPGUARD", rule),))
    )
    assert _heredoc("nft -f /dev/stdin", plan.lines) == (
        f"flush chain inet fw4 BENCHSIPGUARD\nadd rule inet fw4 BENCHSIPGUARD {rule}"
    )
    assert plan.lines[1] == "nft list chain inet fw4 BENCHSIPGUARD > /tmp/owg/rb-<rollback>.nft"
    with pytest.raises(ValueError, match="^Only whole tables are deleted here$"):
        await env.fw.plan_table("ap1", TableRequest(SIP, "delete", override=True))


async def test_add_app_table_prefixes_owg(env: FwEnv) -> None:
    req = TableRequest(
        "",
        "add",
        family="inet",
        name="hwtest",
        chains=(ChainEdit("c", "type filter hook input priority 10; policy accept;"),),
        rules=(("c", "tcp dport 9 counter"),),
    )
    plan = await env.fw.plan_table("ap2", req)
    assert _heredoc("nft -f /dev/stdin", plan.lines).startswith("table inet owg_hwtest {")
    arm = next(line for line in plan.lines if "start-stop-daemon -S" in line)
    assert "nft delete table inet owg_hwtest" in arm
    result = await env.fw.apply_table("ap2", req, plan.digest)
    assert result.verified, result
    objects = {o.key: o.owner for o in (await env.fw.state("ap2")).objects}
    assert objects["inet owg_hwtest"] == "app"
    with pytest.raises(
        ValueError, match=r"^A table name is letters, digits or _ \(it is saved as owg_<name>\)$"
    ):
        await env.fw.plan_table("ap2", TableRequest("", "add", family="inet", name="Bad-Name"))


async def test_include_position_for_table_and_chain(env: FwEnv) -> None:
    plan = await env.fw.plan_table(
        "ap1", TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES, keep="include")
    )
    assert "uci set firewall.owg_bridge_voipdscp='include'" in plan.lines
    assert "uci set firewall.owg_bridge_voipdscp.path='/etc/owg/nft/bridge-voipdscp.nft'" in plan.lines
    assert "uci set firewall.owg_bridge_voipdscp.position='ruleset-post'" in plan.lines
    content = _heredoc("cat > /etc/owg/nft/bridge-voipdscp.nft", plan.lines)
    assert content.startswith(
        "add table bridge voipdscp\nflush table bridge voipdscp\ntable bridge voipdscp {"
    )
    rule = 'oifname { "eth0.2", "wwan0" } tcp dport { 5060, 5061 } counter reject'
    chain = await env.fw.plan_table(
        "ap1", TableRequest(SIP, "edit", override=True, rules=(("BENCHSIPGUARD", rule),), keep="include")
    )
    assert "uci set firewall.owg_inet_fw4_BENCHSIPGUARD.position='table-post'" in chain.lines
    assert _heredoc("cat > /etc/owg/nft/inet-fw4-BENCHSIPGUARD.nft", chain.lines).startswith(
        "chain BENCHSIPGUARD {"
    )


async def test_saved_and_deleted_include_in_sim(env: FwEnv) -> None:
    req = TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES, keep="include")
    plan = await env.fw.plan_table("ap1", req)
    result = await env.fw.apply_table("ap1", req, plan.digest)
    assert result.verified, result
    assert {"saved", "file /etc/owg/nft/bridge-voipdscp.nft"} <= {c.name for c in result.checks}
    gone = TableRequest(VOIP, "delete", override=True)
    plan = await env.fw.plan_table("ap1", gone)
    assert "uci -q delete firewall.owg_bridge_voipdscp" in plan.lines
    assert "rm -f /etc/owg/nft/bridge-voipdscp.nft" in plan.lines
    result = await env.fw.apply_table("ap1", gone, plan.digest)
    assert result.verified, result
    assert "bridge voipdscp" not in {o.key for o in (await env.fw.state("ap1")).objects}


async def test_nft_check_failure_refuses_with_nft_text(env: FwEnv) -> None:
    req = TableRequest(VOIP, "edit", override=True, rules=(("post", "udp dport { 5004 ip dscp set ef"),))
    plan = await env.fw.plan_table("ap1", req)
    result = await env.fw.apply_table("ap1", req, plan.digest)
    assert not result.applied
    assert result.error is not None and result.error.startswith(
        "The router refused the change: Error: syntax error"
    )
    assert ("bridge", "voipdscp") in table_texts(await env.fw.ruleset_text("ap1"))


async def test_table_change_that_cuts_the_app_rolls_back(env: FwEnv) -> None:
    req = TableRequest(
        "",
        "add",
        family="inet",
        name="cut",
        chains=(ChainEdit("c", "type filter hook input priority -10; policy drop;"),),
    )
    plan = await env.fw.plan_table("ap2", req)
    result = await env.fw.apply_table("ap2", req, plan.digest)
    assert not result.applied
    checks = {c.name: c.ok for c in result.checks}
    assert checks["reconnected"] is False and checks["restored"] is True
    assert "inet owg_cut" not in {o.key for o in (await env.fw.state("ap2")).objects}


async def test_guard_live_refuses_unlock_and_edit(env: FwEnv) -> None:
    req = TableRequest(VOIP, "edit", override=True, rules=VOIP_RULES)
    plan = await env.fw.plan_table("ap1", req)
    env.go_live()
    with pytest.raises(GuardLocked):
        await env.fw.apply_table("ap1", req, plan.digest)
