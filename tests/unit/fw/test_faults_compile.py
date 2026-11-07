"""Faults compiled to commands: nft chains on the target's device, tc netem, swconfig, hostapd; what clears
each; what is refused (spec 7.7)."""

from __future__ import annotations

import pytest

from openwrtgui.faults.compile import compile_fault, fault_id
from openwrtgui.faults.model import FaultCaps, FaultRequest, FaultTarget, NetemParams, TargetRef
from openwrtgui.fw.tc import parse_qdiscs
from openwrtgui.timer import arm_command

PANEL_WIFI = FaultTarget("panel", "f4:12:fa:f3:57:68", "192.168.1.30", "phy0-ap0", "phy0-ap0")
PANEL_ETH = FaultTarget("panel", "e4:5f:01:aa:bb:01", "192.168.1.20", "wired", "eth0.1")
NETDEV = FaultCaps("netdev", frozenset(), True, True)
BRIDGE = FaultCaps("bridge", frozenset(), True, True)
REF = TargetRef(None, "192.168.1.30")
DEFAULT_QDISCS = parse_qdiscs(
    "qdisc noqueue 0: dev eth0.1 root refcnt 2\nqdisc noqueue 0: dev phy0-ap0 root refcnt 2\n"
)


def _compile(req: FaultRequest, target: FaultTarget = PANEL_WIFI, caps: FaultCaps = NETDEV, **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {"ports": None, "qdiscs": DEFAULT_QDISCS, "armed": [], "rtp": (4000,)}
    args |= kw
    return compile_fault(
        req, target, caps, args["ports"], args["qdiscs"], args["armed"], args["rtp"], "AP1", id="a1b2c3"
    )  # type: ignore[arg-type]


def test_l3_rtp_in_netdev_plan() -> None:
    c = _compile(FaultRequest("block", REF, flow="rtp_in", loss=30))
    assert c.nft[:2] == (
        "add table netdev benchfault",
        'add chain netdev benchfault fa1b2c3_to { type filter hook egress device "phy0-ap0" priority -500; }',
    )
    assert (
        "add rule netdev benchfault fa1b2c3_to ip daddr 192.168.1.30 udp dport { 4000 } "
        'numgen random mod 100 < 30 counter drop comment "owg:a1b2c3"'
    ) in c.nft
    assert c.chains == ("fa1b2c3_to",)
    assert c.clear == (
        "nft flush chain netdev benchfault fa1b2c3_to",
        "nft delete chain netdev benchfault fa1b2c3_to",
    )


def test_full_loss_is_a_plain_drop_and_flows_match_as_specified() -> None:
    nft = _compile(FaultRequest("block", REF, flow="blackout", loss=100)).nft
    assert (
        'add rule netdev benchfault fa1b2c3_to ip daddr 192.168.1.30 counter drop comment "owg:a1b2c3"' in nft
    )
    assert (
        'add rule netdev benchfault fa1b2c3_from ip saddr 192.168.1.30 counter drop comment "owg:a1b2c3"'
        in nft
    )
    sip = _compile(FaultRequest("block", REF, flow="sip_in")).nft
    assert any(
        "ip daddr 192.168.1.30 meta l4proto { tcp, udp } th sport { 5060, 5061 } counter drop" in s
        for s in sip
    )
    out = _compile(FaultRequest("block", REF, flow="rtp_out", loss=50), rtp=(4000, 4002)).nft
    assert any(
        "ip saddr 192.168.1.30 udp sport { 4000, 4002 } numgen random mod 100 < 50 counter drop" in s
        for s in out
    )


def test_isolate_matches_mac_both_ways() -> None:
    c = _compile(FaultRequest("isolate", REF))
    assert (
        "add rule netdev benchfault fa1b2c3_from ether saddr f4:12:fa:f3:57:68 "
        'counter drop comment "owg:a1b2c3"' in c.nft
    )
    assert (
        "add rule netdev benchfault fa1b2c3_to ether daddr f4:12:fa:f3:57:68 "
        'counter drop comment "owg:a1b2c3"' in c.nft
    )
    assert c.chains == ("fa1b2c3_to", "fa1b2c3_from")


def test_bridge_family_headers() -> None:
    nft = _compile(FaultRequest("isolate", REF), caps=BRIDGE).nft
    assert "add table bridge benchfault" in nft
    assert "add chain bridge benchfault fa1b2c3_to { type filter hook postrouting priority -300; }" in nft
    assert "add chain bridge benchfault fa1b2c3_from { type filter hook prerouting priority -300; }" in nft


def test_only_used_chains_made_and_cleared() -> None:
    c = _compile(FaultRequest("block", REF, flow="rtp_in"))
    assert not any("fa1b2c3_from" in s for s in (*c.nft, *c.clear))


def test_no_family_greys_l2_l3() -> None:
    with pytest.raises(
        ValueError,
        match=r"^This router's nftables cannot filter bridged traffic "
        r"\(needs kmod-nft-netdev or kmod-nft-bridge\)$",
    ):
        _compile(FaultRequest("isolate", REF), caps=FaultCaps(None, frozenset(), True, True))


def test_no_rtp_flow_refused() -> None:
    with pytest.raises(
        ValueError,
        match="^No RTP flow of panel in conntrack: start the call first, or use all_in / all_out.$",
    ):
        _compile(FaultRequest("block", REF, flow="rtp_in"), rtp=())


def test_netem_band_takes_only_the_target() -> None:
    c = _compile(
        FaultRequest("netem", REF, netem=NetemParams(delay_ms=100, jitter_ms=20, loss_pct=1)),
        target=PANEL_ETH,
    )
    assert c.commands == (
        "tc qdisc add dev eth0.1 root handle 1ee7: prio bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1",
        "tc qdisc add dev eth0.1 parent 1ee7:4 handle 1ee8: netem delay 100ms 20ms loss 1%",
        "tc filter add dev eth0.1 parent 1ee7: protocol ip prio 1 u32 "
        "match ip dst 192.168.1.20/32 flowid 1ee7:4",
    )
    assert c.clear == ("tc qdisc del dev eth0.1 root",)


def test_netem_from_target_uses_ifb() -> None:
    c = _compile(
        FaultRequest("netem", REF, netem=NetemParams(delay_ms=50, direction="from")), target=PANEL_ETH
    )
    assert c.commands == (
        "ip link add owgifb0 type ifb",
        "ip link set owgifb0 up",
        "tc qdisc add dev eth0.1 handle ffff: ingress",
        "tc filter add dev eth0.1 parent ffff: protocol ip prio 1 u32 match ip src 192.168.1.20/32 "
        "action mirred egress redirect dev owgifb0",
        "tc qdisc add dev owgifb0 root handle 1ee9: netem delay 50ms",
    )
    assert c.clear == ("tc qdisc del dev eth0.1 ingress", "ip link del owgifb0")
    with pytest.raises(
        ValueError, match="^AP1 has no ifb module: netem from the target is not possible here$"
    ):
        _compile(
            FaultRequest("netem", REF, netem=NetemParams(delay_ms=50, direction="from")),
            target=PANEL_ETH,
            caps=FaultCaps("netdev", frozenset(), False, True),
        )


def test_foreign_qdisc_refused() -> None:
    foreign = parse_qdiscs("qdisc htb 1: dev eth0.1 root refcnt 2 r2q 10 default 0\n")
    with pytest.raises(
        ValueError,
        match=r"^eth0\.1 has a traffic-control qdisc from someone else \(htb 1:\); netem would replace it\.$",
    ):
        _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=10)), target=PANEL_ETH, qdiscs=foreign)


def test_second_netem_on_device_refused() -> None:
    ours = parse_qdiscs(
        "qdisc prio 1ee7: dev eth0.1 root refcnt 2 bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1\n"
    )
    with pytest.raises(ValueError, match=r"^eth0\.1 already has a netem fault; clear it first\.$"):
        _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=10)), target=PANEL_ETH, qdiscs=ours)


def test_netem_values_checked() -> None:
    with pytest.raises(ValueError, match="^Reorder needs a delay$"):
        _compile(FaultRequest("netem", REF, netem=NetemParams(reorder_pct=25)), target=PANEL_ETH)
    with pytest.raises(ValueError, match="^Jitter is at most the delay$"):
        _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=10, jitter_ms=20)), target=PANEL_ETH)
    with pytest.raises(ValueError, match=r"^AP1 has no normal table \(/usr/lib/tc\)$"):
        _compile(
            FaultRequest("netem", REF, netem=NetemParams(delay_ms=10, jitter_ms=5, distribution="normal")),
            target=PANEL_ETH,
        )
    with_tables = FaultCaps("netdev", frozenset({"normal"}), True, True)
    c = _compile(
        FaultRequest("netem", REF, netem=NetemParams(delay_ms=10, jitter_ms=5, distribution="normal")),
        target=PANEL_ETH,
        caps=with_tables,
    )
    assert "netem delay 10ms 5ms distribution normal" in c.commands[1]


def test_ban_deauth_and_ap_down() -> None:
    deauth = _compile(FaultRequest("deauth", REF))
    assert deauth.commands == (
        "ubus call hostapd.phy0-ap0 del_client "
        '\'{"addr":"f4:12:fa:f3:57:68","ban_time":0,"deauth":true,"reason":3}\'',
    )
    assert deauth.clear == () and not deauth.record
    ban = _compile(FaultRequest("ban", REF, ban_s=60))
    assert '"ban_time":60000' in ban.commands[0] and ban.hold_s == 60 and ban.record
    down = _compile(FaultRequest("ap_down", REF))
    assert (down.commands, down.clear) == (
        ("hostapd_cli -i phy0-ap0 disable",),
        ("hostapd_cli -i phy0-ap0 enable",),
    )
    with pytest.raises(
        ValueError,
        match="^A switch port cannot disconnect a Wi-Fi station. For Wi-Fi use Deauth or AP down.$",
    ):
        _compile(FaultRequest("link_down", REF))
    with pytest.raises(ValueError, match=r"^panel is not on Wi-Fi \(no station of an SSID on air\)$"):
        _compile(FaultRequest("deauth", REF), target=PANEL_ETH)


def test_hold_arms_router_timer_and_records() -> None:
    c = _compile(FaultRequest("isolate", REF, hold_s=60))
    assert c.hold_s == 60 and c.record
    assert arm_command("fault-a1b2c3", 60, list(c.clear)).startswith("mkdir -p /tmp/owg && start-stop-daemon")
    with pytest.raises(ValueError, match="^Hold for 5 to 86400 s$"):
        _compile(FaultRequest("isolate", REF, hold_s=2))


def test_fault_id_stable() -> None:
    req = FaultRequest("block", REF, flow="all_in", loss=100)
    assert fault_id(req, []) == fault_id(FaultRequest("block", REF, flow="all_in", loss=100), [])
    assert fault_id(req, ["0f0f0f"]) != fault_id(req, [])
    assert len(fault_id(req, [])) == 6


def test_netem_to_uses_ets_where_the_router_has_no_prio() -> None:
    # AP2 (2026-11-07): no sch_prio, built in or as a module; sch_ets with every band strict is the same
    ets = FaultCaps("bridge", frozenset(), True, True, band="ets")
    c = _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=100)), target=PANEL_ETH, caps=ets)
    assert c.commands[0] == (
        "tc qdisc add dev eth0.1 root handle 1ee7: ets bands 4 strict 4 "
        "priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1"
    )
    assert c.commands[1] == "tc qdisc add dev eth0.1 parent 1ee7:4 handle 1ee8: netem delay 100ms"


def test_netem_to_refused_without_a_band_qdisc_but_from_works() -> None:
    none = FaultCaps("bridge", frozenset(), True, True, band=None)
    with pytest.raises(
        ValueError, match=r"^AP1 has neither sch_prio nor sch_ets, so netem cannot be kept to "
    ):
        _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=10)), target=PANEL_ETH, caps=none)
    c = _compile(
        FaultRequest("netem", REF, netem=NetemParams(delay_ms=10, direction="from")),
        target=PANEL_ETH,
        caps=none,
    )
    assert any(" netem delay 10ms" in x for x in c.commands)


def test_netem_refused_without_the_netem_module() -> None:
    no = FaultCaps("bridge", frozenset(), True, True, netem=False)
    with pytest.raises(ValueError, match=r"^AP1 has no netem \(sch_netem\)$"):
        _compile(FaultRequest("netem", REF, netem=NetemParams(delay_ms=10)), target=PANEL_ETH, caps=no)
