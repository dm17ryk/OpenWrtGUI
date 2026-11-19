"""Connections and the SIP ALG state against AP2's recorded answers (system.json, firewall.json)."""

from pathlib import Path

from openwrtgui.fw.commands import NFT_TEXT
from openwrtgui.system import commands as s
from openwrtgui.system.parse import parse_conntrack, parse_sip_alg
from openwrtgui.system.state import SipAlg
from openwrtgui.transport.fake import load_commands

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"


def test_connections_on_ap2() -> None:
    rows = parse_conntrack(load_commands(AP2 / "system.json")[s.CONNTRACK].stdout)
    assert rows and all(r.proto for r in rows)


def test_sip_alg_on_ap2() -> None:
    ruleset = load_commands(AP2 / "firewall.json")[NFT_TEXT].stdout
    assert parse_sip_alg(ruleset) == SipAlg(state="on", zones=["lan"], ports=[5060])
