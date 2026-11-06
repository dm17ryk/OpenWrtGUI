"""The simulated network: uci with staging folders, rpcd apply/confirm/rollback, swconfig, reachability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.net import commands as c
from openwrtgui.net.parse import interfaces, parse_interface_dump, parse_ip_routes
from openwrtgui.ports.parse import parse_swconfig_show
from openwrtgui.simnet import SimNetwork
from openwrtgui.simulator import SimConnector
from openwrtgui.simwifi import SimWifi
from openwrtgui.transport.base import Unreachable
from openwrtgui.uci import parse_uci_show

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AP2 = (FIXTURES / "sim" / "net" / "ap2.uci").read_text(encoding="utf-8")
S = "/var/run/rpcd/uci-S"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _net(**kw: object) -> tuple[SimNetwork, Clock]:
    clock = Clock()
    return SimNetwork(AP2, clock=clock, **kw), clock  # type: ignore[arg-type]


def _run(net: SimNetwork, command: str) -> str:
    r = net.answer(command)
    assert r is not None, command
    assert r.ok, (command, r.stderr)
    return r.stdout


def _apply(net: SimNetwork, *lines: str, timeout: int = 60, sid: str = "S") -> None:
    _run(net, "\n".join(["set -e", f"mkdir -p /var/run/rpcd/uci-{sid}", *lines]))
    _run(net, f'ubus call uci apply \'{{"rollback":true,"timeout":{timeout},"ubus_rpc_session":"{sid}"}}\'')


def _lan(net: SimNetwork) -> str:
    uci = parse_uci_show(_run(net, c.UCI_NETWORK))
    return str(next(i.address for i in interfaces(uci) if i.name == "lan"))


def test_rollback_restores_after_deadline() -> None:
    net, clock = _net()
    _apply(net, f"uci -P {S} set network.lan.ipaddr='192.168.7.2/24'")
    assert _lan(net) == "192.168.7.2/24" and net.address() == "192.168.7.2"
    assert not net.reachable()
    clock.t += 61
    assert _lan(net) == "192.168.1.2/24" and net.reachable()


def test_confirm_keeps_change() -> None:
    net, clock = _net()
    _apply(net, f"uci -P {S} set network.lan.ipaddr='192.168.1.12/24'")
    _run(net, 'ubus call uci confirm \'{"ubus_rpc_session":"S"}\'')
    clock.t += 120
    assert _lan(net) == "192.168.1.12/24" and net.reachable()
    late = net.answer('ubus call uci confirm \'{"ubus_rpc_session":"S"}\'')
    assert late is not None and not late.ok


def test_staged_changes_stay_in_their_savedir() -> None:
    net, _ = _net()
    _run(net, "\n".join(["set -e", f"mkdir -p {S}", f"uci -P {S} set network.lan.mtu='1400'"]))
    assert "network.lan.mtu" not in parse_uci_show(_run(net, c.UCI_NETWORK))
    _run(net, "\n".join(["set -e", "uci set dhcp.lan.start='50'", "uci commit dhcp"]))
    assert parse_uci_show(_run(net, c.UCI_DHCP))["dhcp.lan.start"] == "50"


def test_script_with_a_new_section_and_a_failing_line() -> None:
    net, _ = _net()
    _run(
        net,
        "\n".join(
            [
                "set -e",
                "h1=$(uci add dhcp host)",
                "uci set dhcp.$h1.name='panel'",
                "uci set dhcp.$h1.mac='f4:12:fa:f3:57:68'",
                "uci commit dhcp",
            ]
        ),
    )
    uci = parse_uci_show(_run(net, c.UCI_DHCP))
    (section,) = [k for k, v in uci.items() if v == "host"]
    assert uci[f"{section}.name"] == "panel"
    bad = net.answer("set -e\nuci set dhcp.lan.start='60'\nuci set nosuch\nuci commit dhcp")
    assert bad is not None and not bad.ok
    assert parse_uci_show(_run(net, c.UCI_DHCP))["dhcp.lan.start"] == "100"  # nothing committed


def test_apply_without_staged_changes_is_refused() -> None:
    net, _ = _net()
    r = net.answer('ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"X"}\'')
    assert r is not None and not r.ok


def test_vlan_without_pc_port_is_unreachable() -> None:
    net, clock = _net()
    vlan1 = next(k.split(".")[1] for k, v in parse_uci_show(AP2).items() if v == "switch_vlan")
    _apply(net, f"uci -P {S} set network.{vlan1}.ports='0 1 2 6t'")
    assert not net.reachable()
    clock.t += 61
    assert net.reachable()


def test_port_disable_is_runtime_and_reload_resets_it() -> None:
    net, _ = _net()
    _run(net, "swconfig dev switch0 port 2 set enable 0")
    port2 = next(
        p for p in parse_swconfig_show("switch0", _run(net, c.swconfig_show("switch0"))).ports if p.num == 2
    )
    assert port2.enabled is False and net.reachable()
    _run(net, "swconfig dev switch0 port 3 set enable 0")
    assert not net.reachable()  # the PC's port
    _apply(net, f"uci -P {S} set network.lan.mtu='1500'")  # any network apply reloads and resets the switch
    sw = parse_swconfig_show("switch0", _run(net, c.swconfig_show("switch0")))
    assert all(p.enabled for p in sw.ports if p.num <= 4) and net.reachable()


def test_reads_the_screens_use() -> None:
    net, _ = _net(leases=[("panel", "f4:12:fa:f3:57:68", "192.168.1.30")], wifi_mirror=True)
    live = {i.name: i for i in parse_interface_dump(json.loads(_run(net, c.INTERFACE_DUMP)))}
    assert live["lan"].up and str(live["lan"].ipv4[0]) == "192.168.1.2/24"
    routes = parse_ip_routes(_run(net, c.ip_routes(4)), 4)
    assert any(r.dst == "192.168.1.0/24" and r.dev == "br-lan" for r in routes)
    assert _run(net, c.SSH_CONNECTION).split() == ["192.168.1.10", "50000", "192.168.1.2", "22"]
    assert "08:3a:88:5c:a8:39" in _run(net, c.ARP)
    assert json.loads(_run(net, c.LEASES))["dhcp_leases"][0]["hostname"] == "panel"
    assert json.loads(_run(net, c.service_list("wifi-mirror")))["wifi-mirror"]["instances"]
    assert json.loads(_run(net, c.service_list("dnsmasq")))["dnsmasq"]["instances"]
    assert json.loads(_run(net, c.switch_features("switch0")))["mirror_option"] == "enable_mirror_rx"
    status = json.loads(_run(net, "ubus call network.interface.lan status"))
    assert status["up"] and status["ipv4-address"] == [{"address": "192.168.1.2", "mask": 24}]
    assert net.answer("iw dev") is None  # not a network command


def test_configured_route_reaches_the_live_table() -> None:
    net, _ = _net()
    _apply(
        net,
        f"r1=$(uci -P {S} add network route)",
        f"uci -P {S} set network.$r1.interface='lan'",
        f"uci -P {S} set network.$r1.target='10.10.0.0/16'",
        f"uci -P {S} set network.$r1.gateway='192.168.1.1'",
    )
    routes = parse_ip_routes(_run(net, c.ip_routes(4)), 4)
    assert any(r.dst == "10.10.0.0/16" and r.gateway == "192.168.1.1" and r.dev == "br-lan" for r in routes)


async def test_address_change_moves_the_host() -> None:
    connector = SimConnector(FIXTURES / "sim")
    t = await connector.connect("192.168.1.2", 22, password=None, key_paths=[Path("k")])
    script = "\n".join(["set -e", f"mkdir -p {S}", f"uci -P {S} set network.lan.ipaddr='192.168.1.12/24'"])
    assert (await t.run(script)).ok
    assert (await t.run('ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"S"}\'')).ok
    moved = await connector.connect("192.168.1.12", 22, password=None, key_paths=[Path("k")])
    assert (await moved.run('ubus call uci confirm \'{"ubus_rpc_session":"S"}\'')).ok
    with pytest.raises(Unreachable):
        await connector.connect("192.168.1.2", 22, password=None, key_paths=[Path("k")])
    assert (await connector.fetch_host_key("192.168.1.12")) == (
        await connector.fetch_host_key("192.168.1.12")
    )


def test_hostapd_acl_lists_are_runtime() -> None:
    wifi = SimWifi((FIXTURES / "sim" / "wifi" / "ap1.uci").read_text(encoding="utf-8"))
    ok = wifi.answer("hostapd_cli -i phy0-ap0 deny_acl ADD_MAC f4:12:fa:f3:57:68")
    assert ok is not None and ok.ok
    shown = wifi.answer("hostapd_cli -i phy0-ap0 deny_acl SHOW")
    assert shown is not None and "f4:12:fa:f3:57:68" in shown.stdout
    gone = wifi.answer("hostapd_cli -i phy0-ap1 deny_acl SHOW")
    assert gone is not None and not gone.ok  # no such interface
    assert wifi.answer("wifi down radio0; wifi up radio0") is not None
    after = wifi.answer("hostapd_cli -i phy0-ap0 deny_acl SHOW")
    assert after is not None and "f4:12:fa:f3:57:68" not in after.stdout
