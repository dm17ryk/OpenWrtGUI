"""tools/record_fixtures.py: the command sets it records and what it hides (no router involved)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.ssh import HostKeyStore

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "record_fixtures.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


rf = _load()

IW_DEV = """phy#0
\tInterface phy0-ap0
\t\tifindex 12
\t\taddr 02:00:00:00:00:02
\t\ttype AP
"""
STATIONS = """Station f4:12:fa:f3:57:68 (on phy0-ap0)
\tinactive time:\t40 ms
Station 3c:84:6a:11:22:33 (on phy0-ap0)
\tinactive time:\t900 ms
"""


class Replay:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, self.answers.get(command, ""), "", 0)


def test_wifi_parked_set_is_exactly_the_planned_commands() -> None:
    assert rf.SETS["wifi-parked"] == (
        "uci -q show wireless",
        'ubus call iwinfo freqlist \'{"device":"radio0"}\'',
        'ubus call iwinfo txpowerlist \'{"device":"radio0"}\'',
        'ubus call iwinfo countrylist \'{"device":"radio0"}\'',
        "iw phy phy0 info",
        "iw dev",
        "uci show",
        # read_wifi's own reads, so the parked recording replays on its own
        "ubus call network.wireless status",
        'ubus call iwinfo phyname \'{"section":"radio0"}\'',
    )


def test_network_set_is_exactly_the_reads_of_the_network_rules() -> None:
    assert rf.SETS["network"] == (
        "uci -X show network",
        "uci -X show dhcp",
        "ubus call network.interface dump",
        "ubus call network.device status",
        "ubus call luci-rpc getDHCPLeases",
        "ubus call luci-rpc getHostHints",
        'echo "$SSH_CONNECTION"',
        "cat /proc/net/arp",
        "ip -j -4 route show table all",
        "ip -j -6 route show table all",
        "ip -j -4 rule show",
        "ip -j -6 rule show",
        "swconfig dev switch0 show",
        "swconfig dev switch0 help",
        "swconfig dev switch0 get arl_table",
        'ubus call luci getSwconfigFeatures \'{"switch":"switch0"}\'',
        'ubus call service list \'{"name":"dnsmasq"}\'',
        'ubus call service list \'{"name":"odhcpd"}\'',
        'ubus call service list \'{"name":"wifi-mirror"}\'',
    )
    assert rf.out_file(Path("tests/fixtures/ap2"), "network") == Path("tests/fixtures/ap2/network.json")


def test_uci_show_secrets_are_hidden() -> None:
    text = (
        "wireless.default_radio0.ssid='OpenWrt'\n"
        "wireless.default_radio0.key='lab key with $pace'\n"
        "network.wan.password='ppp-secret'\n"
        "rpcd.@login[0].password='$p$root'\n"
    )
    out = rf.sanitize(text)
    assert "lab key" not in out and "ppp-secret" not in out and "$p$root" not in out
    assert "wireless.default_radio0.key='<hidden>'" in out and "ssid='OpenWrt'" in out


def test_json_secrets_and_imei_are_hidden() -> None:
    out = rf.sanitize('{"key": "abc", "imei": "356938035643809"}')
    assert '"key": "<hidden>"' in out and "356938035643809" not in out


async def test_wifi_on_commands_follow_the_ap_interface_and_its_stations() -> None:
    t = Replay({"iw dev": IW_DEV, "iw dev phy0-ap0 station dump": STATIONS})
    commands = await rf.wifi_on_commands(t)
    assert commands[:6] == (
        "iw dev phy0-ap0 info",
        "iw dev phy0-ap0 station dump",
        "iw dev phy0-ap0 survey dump",
        "cat /sys/kernel/debug/ieee80211/phy0/statistics/dot11ACKFailureCount",
        "iw phy phy0 info",
        "ubus -v list 'hostapd.*'",
    )
    assert commands[6:] == tuple(
        f"cat /sys/kernel/debug/ieee80211/phy0/netdev:phy0-ap0/stations/{mac}/rc_stats_csv"
        for mac in ("f4:12:fa:f3:57:68", "3c:84:6a:11:22:33")
    )


async def test_wifi_on_needs_a_radio_on_air() -> None:
    t = Replay({"iw dev": "phy#0\n"})
    try:
        await rf.wifi_on_commands(t)
    except RuntimeError as exc:
        assert "no AP interface on phy0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


async def test_recording_sanitizes_each_answer() -> None:
    t = Replay({"uci show": "wireless.default_radio0.key='k'\n"})
    recorded = await rf.run_set(t, ("uci show",))
    assert recorded == {"uci show": {"stdout": "wireless.default_radio0.key='<hidden>'\n", "exit": 0}}


def test_out_path_per_set() -> None:
    assert rf.out_file(Path("tests/fixtures/ap2"), "probe") == Path("tests/fixtures/ap2/commands.json")
    assert rf.out_file(Path("tests/fixtures/ap2"), "wifi-parked") == Path(
        "tests/fixtures/ap2/wifi_parked.json"
    )
    assert rf.out_file(Path("x/wifi_on.json"), "wifi-on") == Path("x/wifi_on.json")


def test_refuses_other_hosts() -> None:
    assert rf.main(["--host", "192.168.1.1", "--identity", "k", "--out", "x", "--set", "wifi-parked"]) == 2


async def test_record_trusts_only_the_known_hosts_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    known = tmp_path / "known_hosts"
    known.write_text("192.168.1.2 ssh-ed25519 AAAA\n", encoding="utf-8")
    seen: dict[str, Path] = {}

    async def connect(
        host: str, port: int, user: str, *, host_keys: HostKeyStore, key_paths: list[Path]
    ) -> Replay:
        seen["known_hosts"] = host_keys.path
        return Replay({})

    async def fetch(*args: object, **kwargs: object) -> None:
        raise AssertionError("took the router's host key on trust")

    monkeypatch.setattr(rf.SshTransport, "connect", staticmethod(connect))
    monkeypatch.setattr(rf, "fetch_host_key", fetch, raising=False)
    monkeypatch.setattr(Replay, "close", _close, raising=False)
    await rf.record("192.168.1.2", Path("k"), known, "wifi-parked")
    assert seen["known_hosts"] == known
    assert known.read_text(encoding="utf-8") == "192.168.1.2 ssh-ed25519 AAAA\n"


def test_known_hosts_option_defaults_to_the_users_file() -> None:
    assert rf.parser().parse_args(["--identity", "k", "--out", "x"]).known_hosts == (
        Path.home() / ".ssh" / "known_hosts"
    )


async def _close(self: Replay) -> None:
    return None


NETDEV_CHECK = (
    "nft -c -f /dev/stdin <<'OWG'\n"
    'table netdev owgcheck { chain c { type filter hook egress device "br-lan" priority -500; }; }\n'
    "OWG"
)
BRIDGE_CHECK = (
    "nft -c -f /dev/stdin <<'OWG'\n"
    "table bridge owgcheck { chain c { type filter hook prerouting priority -300; }; }\n"
    "OWG"
)


def test_firewall_set_is_exactly_the_firewall_and_fault_reads() -> None:
    """Reads only: `nft -c` is nft's check mode and commits nothing; `fw4 print` renders, never loads."""
    assert rf.SETS["firewall"] == (
        "uci -X show firewall",
        "nft -j list ruleset",
        "nft -a list ruleset",
        'for f in /etc/nftables.d/*.nft; do [ -e "$f" ] && { echo "=== $f"; cat "$f"; }; done',
        "ls /rom/etc/nftables.d",
        "tc qdisc show",
        "conntrack -L -p udp",
        "ls /usr/lib/tc",
        "ls /lib/modules/$(uname -r); cat /lib/modules/$(uname -r)/modules.builtin",
        'for c in start-stop-daemon setsid timeout tcpdump conntrack fw4; do command -v "$c"; done',
        "fw4 print",
        "cat /tmp/owg/fault-*.json 2>/dev/null",
        NETDEV_CHECK,
        BRIDGE_CHECK,
    )
    assert rf.out_file(Path("tests/fixtures/ap2"), "firewall") == Path("tests/fixtures/ap2/firewall.json")
