"""DHCP server, fixed addresses, leases: previews, refusals, the conflict check, applies in the simulator."""

from __future__ import annotations

import pytest
from netenv import NetEnv

from openwrtgui.net.dhcp import DhcpRequest, HostRequest
from openwrtgui.net.interfaces import InterfaceRequest
from openwrtgui.net.parse import hosts
from openwrtgui.uci import parse_uci_show

PANEL = "f4:12:fa:f3:57:68"


async def test_turn_on_lan_dhcp_plan(net: NetEnv) -> None:
    plan = await net.service.plan_dhcp("ap2", DhcpRequest("lan", enabled=True))
    assert plan.lines == (
        "set -e",
        "uci -q delete dhcp.lan.ignore",
        "uci commit dhcp",
        "/etc/init.d/dnsmasq reload",
    )
    assert not plan.rollback
    assert (
        "AP1 · bench already serves DHCP on 192.168.1.0/24. Two DHCP servers on one subnet hand out "
        "clashing addresses; on the bench, AP1 is the only DHCP server."
    ) in plan.warnings
    assert "Could not check AP3 · QA stands: no status yet." in plan.warnings


async def test_turning_off_has_no_conflict_warning(net: NetEnv) -> None:
    plan = await net.service.plan_dhcp("ap1", DhcpRequest("lan", enabled=False))
    assert "uci set dhcp.lan.ignore='1'" in plan.lines and plan.warnings == ()


async def test_pool_must_fit(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="The pool 100 to 299 does not fit in 192.168.1.0/24"):
        await net.service.plan_dhcp("ap2", DhcpRequest("lan", start=100, limit=200))


async def test_leasetime_and_option_refusals(net: NetEnv) -> None:
    with pytest.raises(
        ValueError, match=r"Lease time is a number with s, m, h, d or w \(e\.g\. 12h\), or infinite"
    ):
        await net.service.plan_dhcp("ap2", DhcpRequest("lan", leasetime="12 hours"))
    with pytest.raises(ValueError, match="DHCP option codes are 1 to 254"):
        await net.service.plan_dhcp("ap2", DhcpRequest("lan", options=("300,1.2.3.4",)))
    plan = await net.service.plan_dhcp("ap2", DhcpRequest("lan", options=("3,192.168.1.1", "6,192.168.1.1")))
    assert "uci add_list dhcp.lan.dhcp_option='3,192.168.1.1'" in plan.lines


async def test_new_dhcp_section_for_an_interface_without_one(net: NetEnv) -> None:
    guest = InterfaceRequest("guest", create=True, proto="static", device="eth0.3", address="10.3.0.1/24")
    await net.service.apply_interface("ap2", guest)
    plan = await net.service.plan_dhcp("ap2", DhcpRequest("guest", enabled=True, start=10, limit=20))
    assert plan.lines[1:4] == (
        "uci set dhcp.guest='dhcp'",
        "uci set dhcp.guest.interface='guest'",
        "uci set dhcp.guest.start='10'",
    )


async def test_v6_change_reloads_odhcpd(net: NetEnv) -> None:
    plan = await net.service.plan_dhcp("ap2", DhcpRequest("lan", ra="server"))
    assert plan.reloads == ("/etc/init.d/dnsmasq reload", "/etc/init.d/odhcpd reload")


async def test_apply_dhcp_verifies_saved_and_dnsmasq(net: NetEnv) -> None:
    result = await net.service.apply_dhcp("ap2", DhcpRequest("lan", start=50, limit=100, leasetime="1h"))
    assert result.applied and result.verified, result
    assert [c.name for c in result.checks] == ["saved", "dnsmasq"]
    shown = parse_uci_show((await (await net.sim("ap2")).run("uci -X show dhcp")).stdout)
    assert (shown["dhcp.lan.start"], shown["dhcp.lan.limit"], shown["dhcp.lan.leasetime"]) == (
        "50",
        "100",
        "1h",
    )


async def test_add_fixed_host_plan(net: NetEnv) -> None:
    plan = await net.service.plan_hosts(
        "ap2", [HostRequest(None, PANEL, name="panel", ip="192.168.1.30")], []
    )
    assert plan.lines[:5] == (
        "set -e",
        "h1=$(uci add dhcp host)",
        "uci set dhcp.$h1.name='panel'",
        "uci set dhcp.$h1.mac='f4:12:fa:f3:57:68'",
        "uci set dhcp.$h1.ip='192.168.1.30'",
    )


async def test_gets_no_address_sets_ignore(net: NetEnv) -> None:
    plan = await net.service.plan_hosts(
        "ap2", [HostRequest(None, "AA:BB:CC:DD:EE:01", gets_address=False)], []
    )
    assert (
        "uci set dhcp.$h1.mac='aa:bb:cc:dd:ee:01'" in plan.lines
        and "uci set dhcp.$h1.ignore='1'" in plan.lines
    )


async def test_host_refusals_and_warnings(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="f4:12:fa:zz:57:68 is not a MAC address"):
        await net.service.plan_hosts("ap1", [HostRequest(None, "f4:12:fa:zz:57:68")], [])
    with pytest.raises(ValueError, match=r"f4:12:fa:f3:57:68 already has a fixed address \(panel\)"):
        await net.service.plan_hosts("ap1", [HostRequest(None, PANEL, ip="192.168.1.31")], [])
    with pytest.raises(ValueError, match="192.168.1.30 is already fixed for panel"):
        await net.service.plan_hosts("ap1", [HostRequest(None, "aa:bb:cc:dd:ee:01", ip="192.168.1.30")], [])
    plan = await net.service.plan_hosts(
        "ap1", [HostRequest(None, "aa:bb:cc:dd:ee:01", ip="192.168.5.10")], []
    )
    assert "192.168.5.10 is outside every subnet of AP1 · bench" in plan.warnings


async def test_deleting_two_hosts_removes_those_two(net: NetEnv) -> None:
    for i in (1, 2):
        await net.service.apply_hosts(
            "ap1", [HostRequest(None, f"aa:bb:cc:dd:ee:0{i}", ip=f"192.168.1.4{i}")], []
        )
    state = await net.service.state("ap1")
    by_mac = {h.macs[0]: h.section for h in state.hosts}
    assert set(by_mac) == {PANEL, "aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"}
    result = await net.service.apply_hosts("ap1", [], [by_mac[PANEL], by_mac["aa:bb:cc:dd:ee:02"]])
    assert result.verified, result
    left = hosts(parse_uci_show((await (await net.sim("ap1")).run("uci -X show dhcp")).stdout))
    assert [h.macs for h in left] == [("aa:bb:cc:dd:ee:01",)]


async def test_edit_existing_host(net: NetEnv) -> None:
    section = (await net.service.state("ap1")).hosts[0].section
    plan = await net.service.plan_hosts(
        "ap1", [HostRequest(section, PANEL, name="panel", ip="192.168.1.35")], []
    )
    assert plan.lines[1:3] == (f"uci set dhcp.{section}.ip='192.168.1.35'", "uci commit dhcp")


async def test_leases_named_from_hints(net: NetEnv) -> None:
    leases = await net.service.leases("ap1")
    assert [(lease.mac, lease.ip, lease.hostname) for lease in leases] == [(PANEL, "192.168.1.30", "panel")]
