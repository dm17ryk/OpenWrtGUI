"""The firewall, nft, tc and fault-capability parsers against AP2's real answers (recorded read-only,
2026-11-07, Bench Guard clear)."""

import re
from pathlib import Path

from openwrtgui.faults import commands as fc
from openwrtgui.faults.commands import FAMILY_CHECKS
from openwrtgui.faults.service import caps_from
from openwrtgui.fw import commands as c
from openwrtgui.fw.custom import parse_custom
from openwrtgui.fw.nft import parse_ruleset_json, render_table, rule_texts, table_texts, zone_tail
from openwrtgui.fw.parse import firewall_conf
from openwrtgui.fw.tc import parse_qdiscs
from openwrtgui.probe.commands import FAULT_RECORDS
from openwrtgui.transport.fake import load_commands
from openwrtgui.uci import parse_uci_show

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
FW = load_commands(AP2 / "firewall.json")
UCI = parse_uci_show(FW[c.UCI_FIREWALL].stdout)
CONF = firewall_conf(UCI)
RULESET = parse_ruleset_json(FW[c.NFT_JSON].stdout)
TEXT = FW[c.NFT_TEXT].stdout


def test_the_reads_answer() -> None:
    for command in (c.UCI_FIREWALL, c.NFT_JSON, c.NFT_TEXT, c.TC_QDISCS, fc.MODULES, fc.TOOLS, "fw4 print"):
        assert FW[command].exit_status == 0, command
    assert ("inet", "fw4") in RULESET.tables


def test_zones_forwarding_and_rules_as_recorded() -> None:
    zones = {z.name: z for z in CONF.zones}
    assert (zones["lan"].networks, zones["lan"].input, zones["lan"].forward) == (("lan",), "ACCEPT", "ACCEPT")
    # AP2 drops what is forwarded from wan (OpenWrt's default rejects it)
    assert zones["wan"].input == "REJECT" and zones["wan"].forward == "DROP" and zones["wan"].masq
    assert "wan" in zones["wan"].networks
    assert [(f.src, f.dest) for f in CONF.forwardings] == [("lan", "wan")]
    names = [r.name for r in CONF.rules]
    assert {"Allow-DHCP-Renew", "Allow-Ping", "Allow-IGMP"} <= set(names)


def test_zone_tail_is_the_last_rule_of_each_zone_chain() -> None:
    zones = {z.name: z for z in CONF.zones}
    for direction, zone in (("input", "wan"), ("forward", "wan"), ("output", "lan")):
        chain = [r for r in RULESET.rules if r.table == "fw4" and r.chain == f"{direction}_{zone}"]
        assert chain, f"{direction}_{zone}"
        policy = (
            zones[zone].input
            if direction == "input"
            else zones[zone].forward
            if direction == "forward"
            else zones[zone].output
        )
        assert chain[-1].jump == zone_tail(direction, zone, policy)  # type: ignore[arg-type]


def test_every_fw4_comment_names_a_uci_rule() -> None:
    named = {r.name for r in CONF.rules} | {r.name for r in CONF.redirects} | {n.name for n in CONF.nats}
    comments = {
        r.comment.removeprefix("!fw4: ")
        for r in RULESET.rules
        if r.comment and r.comment.startswith("!fw4: ")
    }
    sections = {f"@rule[{i}]" for i in range(len(CONF.rules))}
    built_in = {name for name in comments if not re.match(r"^[A-Za-z0-9 ._-]+$", name) or " " in name}
    assert comments - named - sections - built_in == set()


def test_rule_texts_cover_every_rule_handle() -> None:
    texts = rule_texts(TEXT)
    for r in RULESET.rules:
        assert (r.family, r.table, r.handle) in texts, (r.chain, r.handle)
    assert not any(re.search(r"packets \d+ bytes", t) for t in texts.values())


def test_table_texts_round_trip() -> None:
    tables = table_texts(TEXT)
    assert set(tables) == set(RULESET.tables)
    for key, table in tables.items():
        assert table_texts(render_table(table))[key] == table


def test_custom_files_and_qdiscs_parse() -> None:
    files = parse_custom(FW[c.CUSTOM_FILES].stdout, FW[c.ROM_CUSTOM].stdout)
    assert files and all(f.path.startswith("/etc/nftables.d/") for f in files)
    assert all(f.from_image for f in files)
    qdiscs = parse_qdiscs(FW[c.TC_QDISCS].stdout)
    assert any(q.dev == "eth0" and q.kind == "fq_codel" and q.root for q in qdiscs)


def test_fault_family_is_bridge_on_ap2() -> None:
    # AP2's kernel has no netdev egress hook ("Chain of type ... is not supported"); bridge works
    netdev, bridge = (FW[FAMILY_CHECKS[name]] for name in ("netdev", "bridge"))
    assert netdev.exit_status == 1 and "not supported" in netdev.stderr
    assert bridge.exit_status == 0
    family = next(name for name, check in FAMILY_CHECKS.items() if FW[check].exit_status == 0)
    assert family == "bridge"


def test_tools_modules_and_netem_tables() -> None:
    tools = FW[fc.TOOLS].stdout.split()
    for tool in ("start-stop-daemon", "setsid", "timeout", "tcpdump", "conntrack", "fw4"):
        assert any(path.endswith(f"/{tool}") for path in tools), tool
    modules = FW[fc.MODULES].stdout.split()
    assert {"ifb.ko", "sch_netem.ko", "nft_numgen.ko"} <= set(modules)
    assert not any("sch_prio" in m for m in modules)  # neither a module file nor built in
    assert FW[fc.TC_TABLES].exit_status == 1  # no /usr/lib/tc: only uniform jitter on AP2
    caps = caps_from("bridge", "", FW[fc.MODULES].stdout, FW[fc.TOOLS].stdout)
    assert (caps.band, caps.netem, caps.ifb, caps.conntrack, caps.distributions) == (
        "ets",
        True,
        True,
        True,
        frozenset(),
    )
    assert FW[fc.CONNTRACK_UDP].exit_status == 0
    assert FW[FAULT_RECORDS].exit_status == 1  # nothing armed
