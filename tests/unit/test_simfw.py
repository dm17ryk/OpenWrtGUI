"""The simulated firewall: fw4 rendered from the firewall config, runtime nft tables, tc, router-side timers,
the app's /tmp/owg files and a tcpdump stream; and what it does to the PC's reach."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.faults.commands import TOOLS
from openwrtgui.fw.nft import parse_ruleset_json, rule_texts
from openwrtgui.fw.tc import u32_match
from openwrtgui.simfw import SimFirewall
from openwrtgui.simnet import SimNetwork
from openwrtgui.simulator import SimConnector
from openwrtgui.timer import alive_command, arm_command, cancel_command
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport, SimState
from openwrtgui.uci import parse_uci_show

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AP2 = (FIXTURES / "sim" / "net" / "ap2.uci").read_text(encoding="utf-8")
AP1_RUNTIME = json.loads((FIXTURES / "sim" / "fw" / "ap1.json").read_text(encoding="utf-8"))
S = "/var/run/rpcd/uci-S"
LAN_ZONE = "firewall.cfg02dc81"
PIN = "firewall.owg_pin_ssh"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _sim(
    runtime: dict[str, object] | None = None, families: frozenset[str] = frozenset({"netdev", "bridge"})
):  # type: ignore[no-untyped-def]
    clock = Clock()
    net = SimNetwork(AP2, clock=clock)
    fw = SimFirewall(net, runtime or {}, families=families, clock=clock)
    return ReplayTransport({}, SimState(net=net, fw=fw)), net, fw, clock


async def _ok(t: ReplayTransport, command: str) -> str:
    r = await t.run(command)
    assert r.ok, (command, r.stderr)
    return r.stdout


async def _apply_firewall(t: ReplayTransport, *lines: str, timeout: int = 60) -> None:
    await _ok(t, "\n".join(["set -e", f"mkdir -p {S}", *lines]))
    await _ok(t, f'ubus call uci apply \'{{"rollback":true,"timeout":{timeout},"ubus_rpc_session":"S"}}\'')


def _nft(script: str, check: bool = False) -> str:
    return f"nft {'-c ' if check else ''}-f /dev/stdin <<'OWG'\n{script}\nOWG"


async def test_block_all_without_pin_is_unreachable() -> None:
    t, net, _fw, _clock = _sim()
    assert net.reachable()
    await _apply_firewall(t, f"uci -P {S} set {LAN_ZONE}.input='DROP'")
    assert not net.reachable()


async def test_pin_keeps_ssh() -> None:
    t, net, _fw, _clock = _sim()
    await _apply_firewall(
        t,
        f"uci -P {S} set {LAN_ZONE}.input='REJECT'",
        f"uci -P {S} set {PIN}=rule",
        f"uci -P {S} set {PIN}.name='Allow SSH from this PC'",
        f"uci -P {S} set {PIN}.src='lan'",
        f"uci -P {S} set {PIN}.src_ip='192.168.1.10'",
        f"uci -P {S} set {PIN}.proto='tcp'",
        f"uci -P {S} set {PIN}.dest_port='22'",
        f"uci -P {S} set {PIN}.target='ACCEPT'",
    )
    assert net.reachable()


async def test_firewall_rollback_restores_after_deadline() -> None:
    t, net, _fw, clock = _sim()
    await _apply_firewall(t, f"uci -P {S} set {LAN_ZONE}.input='DROP'")
    clock.t += 61
    shown = parse_uci_show(await _ok(t, "uci -X show firewall"))
    assert shown[f"{LAN_ZONE}.input"] == "ACCEPT"
    assert net.reachable()


async def test_ruleset_renders_fw4_from_the_config() -> None:
    t, _net, _fw, _clock = _sim()
    await _apply_firewall(t, f"uci -P {S} set firewall.cfg03dc81.input='DROP'")
    ruleset = parse_ruleset_json(await _ok(t, "nft -j list ruleset"))
    tail = [r for r in ruleset.rules if r.table == "fw4" and r.chain == "input_wan"][-1]
    assert tail.jump == "drop_from_wan"
    ping = next(r for r in ruleset.rules if r.comment == "!fw4: Allow-Ping")
    assert ping.chain == "input_wan" and ping.packets is not None
    texts = rule_texts(await _ok(t, "nft -a list ruleset"))
    assert any('comment "!fw4: Allow-Ping"' in text for text in texts.values())


async def test_runtime_table_add_and_list() -> None:
    t, _net, _fw, _clock = _sim()
    table = (
        "table inet owg_t {\n\tchain c {\n\t\ttype filter hook input priority 10; policy accept;\n"
        "\t\ttcp dport 9 counter\n\t}\n}"
    )
    await _ok(t, _nft(table, check=True))
    assert not (await t.run("nft list table inet owg_t")).ok  # a check commits nothing
    await _ok(t, _nft(table))
    assert "tcp dport 9 counter" in await _ok(t, "nft list table inet owg_t")
    ruleset = parse_ruleset_json(await _ok(t, "nft -j list ruleset"))
    assert ("inet", "owg_t") in ruleset.tables
    await _ok(t, "nft delete table inet owg_t")
    assert ("inet", "owg_t") not in parse_ruleset_json(await _ok(t, "nft -j list ruleset")).tables


async def test_harness_objects_on_ap1() -> None:
    t, _net, _fw, _clock = _sim(AP1_RUNTIME)
    ruleset = parse_ruleset_json(await _ok(t, "nft -j list ruleset"))
    assert ("bridge", "voipdscp") in ruleset.tables
    assert any(c.table == "fw4" and c.name == "BENCHSIPGUARD" for c in ruleset.chains)
    conntrack = await _ok(t, "conntrack -L -p udp")
    assert "src=192.168.1.30" in conntrack and "sport=4000" in conntrack


async def test_family_without_support_refused() -> None:
    t, _net, _fw, _clock = _sim(families=frozenset({"bridge"}))
    netdev = 'table netdev owgcheck { chain c { type filter hook egress device "br-lan" priority -500; }; }'
    r = await t.run(_nft(netdev, check=True))
    assert r.exit_status == 1 and "Error: Could not process rule: No such file or directory" in r.stderr
    bridge = "table bridge owgcheck { chain c { type filter hook prerouting priority -300; }; }"
    assert (await t.run(_nft(bridge, check=True))).ok


async def test_a_block_closed_twice_on_one_line_is_a_syntax_error() -> None:
    # AP2 2026-11-07: nft wants a newline or ';' between a chain's '}' and the table's
    t, _net, _fw, _clock = _sim()
    r = await t.run(
        _nft("table bridge owgcheck { chain c { type filter hook prerouting priority -300; } }", check=True)
    )
    assert r.exit_status == 1
    assert "syntax error, unexpected '}', expecting newline or semicolon" in r.stderr


async def test_qdiscs_shown_for_one_device_leave_out_the_device() -> None:
    # iproute2 prints `dev X` only when the listing is not already filtered by device (AP2, 2026-11-07)
    t, _net, _fw, _clock = _sim()
    assert "dev eth0 " in await _ok(t, "tc qdisc show")
    one = await _ok(t, "tc qdisc show dev eth0")
    assert one.startswith("qdisc fq_codel 0: root ") and " dev " not in one


async def test_tools_are_looked_up_one_by_one() -> None:
    # busybox ash's `command -v a b` prints the first name only; the read asks for each tool
    t, _net, _fw, _clock = _sim()
    out = await _ok(t, TOOLS)
    assert [line.rsplit("/", 1)[1] for line in out.splitlines()] == [
        "start-stop-daemon",
        "setsid",
        "timeout",
        "tcpdump",
        "conntrack",
        "fw4",
    ]


async def test_timer_fires_and_cancel_stops_it() -> None:
    t, _net, _fw, clock = _sim()
    await _ok(t, "touch /tmp/owg-flag")
    await _ok(t, arm_command("t1", 10, ["rm -f /tmp/owg-flag"]))
    await _ok(t, alive_command("t1"))
    clock.t += 11
    assert not (await t.run("cat /tmp/owg-flag")).ok
    assert not (await t.run(alive_command("t1"))).ok

    await _ok(t, "touch /tmp/owg-flag")
    await _ok(t, arm_command("t2", 10, ["rm -f /tmp/owg-flag"]))
    await _ok(t, cancel_command("t2"))
    clock.t += 11
    assert (await t.run("cat /tmp/owg-flag")).ok


async def test_timer_lines_reach_the_other_simulators() -> None:
    """A held fault's clear line can be swconfig: the timer runs it through the whole router."""
    t, net, _fw, clock = _sim()
    await _ok(t, "swconfig dev switch0 port 2 set enable 0")
    await _ok(t, arm_command("fault-a1b2c3", 5, ["swconfig dev switch0 port 2 set enable 1"]))
    clock.t += 6
    assert "enable: 1" in (await _ok(t, "swconfig dev switch0 show")).split("Port 2:")[1].split("Port 3:")[0]


async def test_tc_netem_add_show_del() -> None:
    t, _net, _fw, _clock = _sim()
    before = await _ok(t, "tc qdisc show")
    await _ok(
        t, "tc qdisc add dev eth0.1 root handle 1ee7: prio bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1"
    )
    await _ok(t, "tc qdisc add dev eth0.1 parent 1ee7:4 handle 1ee8: netem delay 100ms")
    await _ok(
        t,
        "tc filter add dev eth0.1 parent 1ee7: protocol ip prio 1 u32 "
        "match ip dst 192.168.1.30/32 flowid 1ee7:4",
    )
    shown = await _ok(t, "tc qdisc show dev eth0.1")
    assert "qdisc netem 1ee8: parent 1ee7:4" in shown and "delay 100ms" in shown  # filtered: no `dev`
    assert u32_match("192.168.1.30", "dst") in await _ok(t, "tc filter show dev eth0.1 parent 1ee7:")
    await _ok(t, "tc qdisc del dev eth0.1 root")
    assert await _ok(t, "tc qdisc show") == before


async def test_fault_record_written_and_read_on_the_router_clock() -> None:
    t, _net, _fw, clock = _sim()
    assert not (await t.run("cat /tmp/owg/fault-*.json 2>/dev/null")).ok
    record = '{"id":"a1b2c3","kind":"block",'
    await _ok(t, f"printf '%s\"armed_at\":%s}}\\n' '{record}' \"$(date +%s)\" > /tmp/owg/fault-a1b2c3.json")
    line = (await _ok(t, "cat /tmp/owg/fault-*.json 2>/dev/null")).strip()
    assert json.loads(line) == {"id": "a1b2c3", "kind": "block", "armed_at": int(clock.t)}
    assert int((await _ok(t, "date +%s")).strip()) == int(clock.t)


def test_tcpdump_stream_is_pcap() -> None:
    _t, _net, fw, _clock = _sim()
    stream = fw.stream("timeout 3 tcpdump -i br-lan -U -s 0 -w - 'not (host 192.168.1.10 and tcp port 22)'")
    assert stream is not None and stream[:4] == bytes.fromhex("d4c3b2a1")
    assert fw.stream("tcpdump -i nosuchdev -w -") is None


async def test_unknown_commands_are_left_to_the_others() -> None:
    _t, _net, fw, _clock = _sim()
    assert fw.answer("iw dev") is None
    assert isinstance(fw.answer("nft -j list ruleset"), CommandResult)


async def test_ap_down_and_back() -> None:
    """hostapd_cli disable / enable on ap1, whose radio is on air (the Wi-Fi AP down fault)."""
    connector = SimConnector(FIXTURES / "sim")
    t = await connector.connect("192.168.1.1", 22, password=None, key_paths=[Path("k")])
    assert "state=ENABLED" in (await t.run("hostapd_cli -i phy0-ap0 status")).stdout
    assert (await t.run("hostapd_cli -i phy0-ap0 disable")).ok
    assert "state=DISABLED" in (await t.run("hostapd_cli -i phy0-ap0 status")).stdout
    assert (await t.run("hostapd_cli -i phy0-ap0 enable")).ok
    assert "state=ENABLED" in (await t.run("hostapd_cli -i phy0-ap0 status")).stdout
