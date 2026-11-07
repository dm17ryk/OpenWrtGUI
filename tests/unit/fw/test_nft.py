"""nft output: `nft -j list ruleset` (structure, hooks, counters) and `nft -a list ruleset` (rule text)."""

from __future__ import annotations

import json

from openwrtgui.fw.nft import (
    ChainText,
    TableText,
    listing_text,
    parse_ruleset_json,
    render_table,
    rule_texts,
    table_shape,
    table_texts,
    zone_tail,
)

TEXT = """table inet fw4 { # handle 1
\tchain input { # handle 1
\t\ttype filter hook input priority filter; policy accept;
\t\tiifname "eth0.2" jump input_wan comment "!fw4: Handle wan IPv4/IPv6 input traffic" # handle 7
\t}
\tchain input_wan { # handle 9
\t\ticmp type echo-request counter packets 12 bytes 1008 accept comment "!fw4: Allow-Ping" # handle 40
\t\tjump reject_from_wan # handle 41
\t}
\tset lan_hosts { # handle 12
\t\ttype ipv4_addr
\t\telements = { 192.168.1.20, 192.168.1.30 }
\t}
}
table bridge voipdscp { # handle 2
\tchain post { # handle 1
\t\ttype filter hook postrouting priority 0; policy accept;
\t\tudp dport 5004 ip dscp set ef counter packets 48112 bytes 0 # handle 3
\t\tudp dport { 5060, 5061 } ip dscp set ef counter packets 1904 bytes 0 # handle 4
\t}
}
"""

JSON = json.dumps(
    {
        "nftables": [
            {"metainfo": {"version": "1.1.1", "json_schema_version": 1}},
            {"table": {"family": "inet", "name": "fw4", "handle": 1}},
            {
                "chain": {
                    "family": "inet",
                    "table": "fw4",
                    "name": "input",
                    "handle": 1,
                    "type": "filter",
                    "hook": "input",
                    "prio": 0,
                    "policy": "accept",
                }
            },
            {"chain": {"family": "inet", "table": "fw4", "name": "input_wan", "handle": 9}},
            {
                "rule": {
                    "family": "inet",
                    "table": "fw4",
                    "chain": "input_wan",
                    "handle": 40,
                    "comment": "!fw4: Allow-Ping",
                    "expr": [
                        {
                            "match": {
                                "op": "==",
                                "left": {"payload": {"protocol": "icmp", "field": "type"}},
                                "right": "echo-request",
                            }
                        },
                        {"counter": {"packets": 12, "bytes": 1008}},
                        {"accept": None},
                    ],
                }
            },
            {
                "rule": {
                    "family": "inet",
                    "table": "fw4",
                    "chain": "input_wan",
                    "handle": 41,
                    "expr": [{"jump": {"target": "reject_from_wan"}}],
                }
            },
            {"set": {"family": "inet", "table": "fw4", "name": "lan_hosts", "handle": 12}},
            {"table": {"family": "netdev", "name": "benchfault", "handle": 3}},
            {
                "chain": {
                    "family": "netdev",
                    "table": "benchfault",
                    "name": "fa1b2c3_to",
                    "handle": 1,
                    "type": "filter",
                    "hook": "egress",
                    "prio": -500,
                    "policy": "accept",
                    "dev": "phy0-ap0",
                }
            },
        ]
    }
)


def test_ruleset_json() -> None:
    r = parse_ruleset_json(JSON)
    assert r.tables == (("inet", "fw4"), ("netdev", "benchfault"))
    chains = {(c.table, c.name): c for c in r.chains}
    assert (chains[("fw4", "input")].hook, chains[("fw4", "input")].priority) == ("input", 0)
    assert chains[("fw4", "input")].policy == "accept"
    assert chains[("fw4", "input_wan")].hook is None
    egress = chains[("benchfault", "fa1b2c3_to")]
    assert (egress.hook, egress.priority, egress.device) == ("egress", -500, "phy0-ap0")
    rules = {rule.handle: rule for rule in r.rules}
    assert (rules[40].comment, rules[40].packets, rules[40].bytes) == ("!fw4: Allow-Ping", 12, 1008)
    assert rules[41].jump == "reject_from_wan" and rules[41].packets is None
    assert [s.name for s in r.sets] == ["lan_hosts"]


def test_ruleset_json_ignores_what_it_does_not_know() -> None:
    r = parse_ruleset_json('{"nftables": [{"flowtable": {"name": "ft"}}, {"rule": {"family": "inet"}}]}')
    assert (r.tables, r.chains, r.rules, r.sets) == ((), (), (), ())


def test_rule_text_by_handle() -> None:
    texts = rule_texts(TEXT)
    assert texts[("inet", "fw4", 40)] == 'icmp type echo-request counter accept comment "!fw4: Allow-Ping"'
    assert texts[("inet", "fw4", 41)] == "jump reject_from_wan"
    assert texts[("bridge", "voipdscp", 4)] == "udp dport { 5060, 5061 } ip dscp set ef counter"
    assert ("inet", "fw4", 12) not in texts  # a set, not a rule


def test_table_round_trip() -> None:
    t = table_texts(TEXT)[("bridge", "voipdscp")]
    assert t.chains[0].name == "post"
    assert t.chains[0].declaration == "type filter hook postrouting priority 0; policy accept;"
    assert t.chains[0].rules == (
        "udp dport 5004 ip dscp set ef counter",
        "udp dport { 5060, 5061 } ip dscp set ef counter",
    )
    assert table_texts(render_table(t))[("bridge", "voipdscp")] == t


def test_table_sets_carried_as_they_are() -> None:
    fw4 = table_texts(TEXT)[("inet", "fw4")]
    assert fw4.sets == (
        "\tset lan_hosts {\n\t\ttype ipv4_addr\n\t\telements = { 192.168.1.20, 192.168.1.30 }\n\t}",
    )
    assert [c.name for c in fw4.chains] == ["input", "input_wan"]
    assert fw4.chains[1].declaration is None
    assert table_texts(render_table(fw4))[("inet", "fw4")] == fw4


def test_zone_tail() -> None:
    assert zone_tail("input", "wan", "REJECT") == "reject_from_wan"
    assert zone_tail("output", "lan", "ACCEPT") == "accept_to_lan"
    assert zone_tail("forward", "lan", "DROP") == "drop_to_lan"


def _table(rule: str) -> str:
    return f"table bridge voipdscp {{\n\tchain post {{\n\t\t{rule}\n\t}}\n}}\n"


def test_a_listing_compares_without_its_moving_counters() -> None:
    # a live table counts packets between the snapshot and the restore check (final review, Important 1)
    before = _table("udp dport 5004 counter packets 3 bytes 120")
    after = _table("udp dport 5004 counter packets 97 bytes 4100").rstrip()
    assert listing_text(before) == listing_text(after)
    assert listing_text(before) != listing_text(_table("udp dport 5006 counter packets 3 bytes 120"))


def test_table_shape_ignores_how_nft_prints_a_rule() -> None:
    # nft lists `ip saddr 10.0.0.1/32` as `ip saddr 10.0.0.1` and `{22,80}` as `{ 22, 80 }` (Important 2)
    rules = ("ip saddr 10.0.0.1/32 counter", "tcp dport {22,80} accept")
    typed = TableText("ip", "owg_t", (), (ChainText("c", "type filter hook input priority 0;", rules),))
    listing = (
        "table ip owg_t {\n\tchain c {\n\t\ttype filter hook input priority filter; policy accept;\n"
        "\t\tip saddr 10.0.0.1 counter packets 0 bytes 0\n\t\ttcp dport { 22, 80 } accept\n\t}\n}\n"
    )
    listed = table_texts(listing)[("ip", "owg_t")]
    assert table_shape(listed) == table_shape(typed) == (("c", 2),)
    fewer = TableText("ip", "owg_t", (), (ChainText("c", None, ("ip saddr 10.0.0.1 counter",)),))
    assert table_shape(fewer) != table_shape(listed)
