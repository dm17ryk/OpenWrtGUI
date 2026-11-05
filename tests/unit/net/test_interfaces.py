"""Router addresses: the plan, the refusals, All options, and apply with rollback in the simulator."""

from __future__ import annotations

import pytest
from netenv import NetEnv

from openwrtgui.net.interfaces import InterfaceRequest

SESSION_SET = "uci -P /var/run/rpcd/uci-<session> set"
APPLY = 'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"<session>"}\''


async def test_state_marks_own_and_dynamic_interfaces(net: NetEnv) -> None:
    state = await net.service.state("ap2")
    views = {v.conf.name if v.conf else v.live.name: v for v in state.interfaces}  # type: ignore[union-attr]
    assert state.own_interface == "lan" and views["lan"].own
    assert (state.pc_ip, state.router_ip) == ("192.168.1.10", "192.168.1.2")
    assert views["lte_4"].conf is None and views["lte_4"].dynamic_parent == "lte"
    assert {p.name: p.label for p in state.protocols}["qmi"] == "LTE (QMI)"
    assert "none" in {p.name for p in state.protocols}


async def test_lan_address_change_plan(net: NetEnv) -> None:
    plan = await net.service.plan_interface("ap2", InterfaceRequest("lan", address="192.168.1.12/24"))
    assert f"{SESSION_SET} network.lan.ipaddr='192.168.1.12/24'" in plan.lines
    assert APPLY in plan.lines
    assert plan.rollback and plan.target_host == "192.168.1.12"
    assert (
        "Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.12 again "
        "and confirm, the router restores its previous network settings by itself."
    ) in plan.warnings


async def test_own_interface_cannot_be_deleted_or_leave_static(net: NetEnv) -> None:
    with pytest.raises(
        ValueError, match="lan carries this app's connection to AP2 · office; it cannot be deleted here."
    ):
        await net.service.plan_interface("ap2", InterfaceRequest("lan", delete=True))
    with pytest.raises(
        ValueError,
        match="lan carries this app's connection to AP2 · office; with DHCP client the app has no known",
    ):
        await net.service.plan_interface("ap2", InterfaceRequest("lan", proto="dhcp"))


async def test_bare_address_and_bad_fields_are_refused(net: NetEnv) -> None:
    with pytest.raises(ValueError, match=r"Write the address with its prefix, e\.g\. 192\.168\.1\.2/24"):
        await net.service.plan_interface("ap2", InterfaceRequest("lan", address="192.168.1.12"))
    with pytest.raises(ValueError, match="MTU is 68 to 9000"):
        await net.service.plan_interface("ap2", InterfaceRequest("lan", mtu=10000))
    with pytest.raises(ValueError, match="192.168.1.300 is not an IPv4 address"):
        await net.service.plan_interface("ap2", InterfaceRequest("lan", gateway="192.168.1.300"))
    with pytest.raises(ValueError, match="There is no interface named wan9"):
        await net.service.plan_interface("ap2", InterfaceRequest("wan9", mtu=1400))


async def test_proto_change_drops_static_fields(net: NetEnv) -> None:
    to_static = await net.service.plan_interface(
        "ap2", InterfaceRequest("wan", proto="static", address="10.0.0.2/24", gateway="10.0.0.1")
    )
    assert f"{SESSION_SET} network.wan.proto='static'" in to_static.lines
    assert f"{SESSION_SET} network.wan.ipaddr='10.0.0.2/24'" in to_static.lines
    await net.service.apply_interface(
        "ap2", InterfaceRequest("wan", proto="static", address="10.0.0.2/24", gateway="10.0.0.1")
    )
    back = await net.service.plan_interface("ap2", InterfaceRequest("wan", proto="dhcp"))
    assert "uci -P /var/run/rpcd/uci-<session> -q delete network.wan.ipaddr" in back.lines
    assert "uci -P /var/run/rpcd/uci-<session> -q delete network.wan.gateway" in back.lines
    with pytest.raises(ValueError, match="Give wan6 an address, e.g. 192.168.1.2/24"):
        await net.service.plan_interface("ap2", InterfaceRequest("wan6", proto="static"))


async def test_dynamic_interface_is_read_only(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="lte_4 is made by lte at run time; change lte instead."):
        await net.service.plan_interface("ap2", InterfaceRequest("lte_4", mtu=1400))


async def test_create_interface_and_name_refusals(net: NetEnv) -> None:
    plan = await net.service.plan_interface(
        "ap2", InterfaceRequest("guest", create=True, proto="static", device="eth0.3", address="10.3.0.1/24")
    )
    assert f"{SESSION_SET} network.guest='interface'" in plan.lines
    assert any("Put guest in a firewall zone" in w for w in plan.warnings)
    with pytest.raises(ValueError, match="An interface name is 1 to 15 letters, digits or _"):
        await net.service.plan_interface("ap2", InterfaceRequest("guest-net", create=True, proto="none"))
    with pytest.raises(ValueError, match="There is already an interface named wan"):
        await net.service.plan_interface("ap2", InterfaceRequest("wan", create=True, proto="none"))


async def test_all_options_from_proto_handler(net: NetEnv) -> None:
    rows = {r.name: r for r in await net.service.interface_options("ap2", "lan")}
    assert rows["ipaddr"].control == "Address" and rows["ipaddr"].value == "192.168.1.2/24"
    assert rows["ip6addr"].control is None and rows["ip6addr"].config == "network"
    qmi = {r.name: r for r in await net.service.interface_options("ap2", "lte")}
    assert qmi["apn"].value == "uinternet" and qmi["password"].editor == "secret"


async def test_target_outside_pc_subnet_warns(net: NetEnv) -> None:
    plan = await net.service.plan_interface("ap2", InterfaceRequest("lan", address="10.0.0.2/24"))
    assert (
        "This PC (192.168.1.10) is not in 10.0.0.0/24: the app reaches 10.0.0.2 only through a route, "
        "otherwise the change rolls back."
    ) in plan.warnings


async def test_apply_lan_in_sim_follows_and_verifies(net: NetEnv) -> None:
    plan = await net.service.plan_interface("ap2", InterfaceRequest("lan", address="192.168.1.12/24"))
    result = await net.service.apply_interface(
        "ap2", InterfaceRequest("lan", address="192.168.1.12/24"), plan.digest
    )
    assert result.applied and result.verified, result
    assert [c.name for c in result.checks] == ["reconnected", "confirmed", "interface lan", "saved"]
    assert net.rec("ap2").host == "192.168.1.12" and result.host == "192.168.1.12"
    back = await net.service.apply_interface("ap2", InterfaceRequest("lan", address="192.168.1.2/24"))
    assert back.verified and net.rec("ap2").host == "192.168.1.2"
    assert "verify network" in net.audit_lines()


async def test_fields_other_than_the_address_are_proven_by_the_saved_config(net: NetEnv) -> None:
    """An MTU or bridge edit leaves lan up with its address, so "up" proves nothing about it: the saved
    config must hold every field asked for (Codex review, PR #23)."""
    result = await net.service.apply_interface(
        "ap2", InterfaceRequest("lan", mtu=1400, bridge_ports=("eth0.1", "eth0.3"))
    )
    assert result.verified, result
    saved = next(c for c in result.checks if c.name == "saved")
    assert saved.ok is True


async def test_apply_with_stale_digest_is_refused(net: NetEnv) -> None:
    from openwrtgui.wifi.service import PreviewChanged

    with pytest.raises(PreviewChanged):
        await net.service.apply_interface("ap2", InterfaceRequest("lan", mtu=1400), "0000000000000000")


async def test_apply_refused_while_guard_live(net: NetEnv) -> None:
    from openwrtgui.guard.bench_guard import GuardLocked

    net.go_live()
    with pytest.raises(GuardLocked):
        await net.service.apply_interface("ap2", InterfaceRequest("lan", mtu=1400))
