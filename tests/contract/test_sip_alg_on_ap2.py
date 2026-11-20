"""The SIP ALG switch against AP2's recorded firewall (firewall.json): its ten helpers, lan's chain, and the
change Off would make."""

from pathlib import Path

from openwrtgui.fw.commands import NFT_TEXT, UCI_FIREWALL
from openwrtgui.fw.sip import SipAlgRequest, sip_alg_zones, sip_ops
from openwrtgui.system.parse import available_helpers, zone_helpers
from openwrtgui.transport.fake import load_commands
from openwrtgui.uci import UciOp, parse_uci_show

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
TEN = ["amanda", "RAS", "Q.931", "irc", "netbios-ns", "pptp", "sane", "sip", "snmp", "tftp"]


def _recorded() -> tuple[dict[str, str], str]:
    commands = load_commands(AP2 / "firewall.json")
    return parse_uci_show(commands[UCI_FIREWALL].stdout), commands[NFT_TEXT].stdout


def test_helpers_on_ap2() -> None:
    _uci, ruleset = _recorded()
    assert available_helpers(ruleset) == TEN
    assert zone_helpers(ruleset) == {"lan": TEN}


def test_lan_off_on_ap2() -> None:
    uci, ruleset = _recorded()
    zones = sip_alg_zones(uci, ruleset)
    assert zones.state == "on" and [(z.zone, z.section, z.sip) for z in zones.zones] == [
        ("lan", "cfg02dc81", True)
    ]
    _zone, ops = sip_ops(uci, ruleset, SipAlgRequest(zone="lan", on=False))
    assert ops == [
        UciOp("set", "firewall.cfg02dc81.auto_helper", "0"),
        *[UciOp("add_list", "firewall.cfg02dc81.helper", h) for h in TEN if h != "sip"],
    ]
