"""Fault targets: stations, host hints, leases, ARP and known devices merged by MAC; the PC and the router
itself are never a target."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.faults.model import TargetRef
from openwrtgui.faults.targets import lan_wired_device, read_targets, resolve, router_macs
from openwrtgui.store.settings import KnownDevice

PANEL_WIFI = "f4:12:fa:f3:57:68"
PANEL_ETH = "e4:5f:01:aa:bb:01"
PC_MAC = "08:3a:88:5c:a8:39"


async def _targets(env: FwEnv, router_id: str):  # type: ignore[no-untyped-def]
    t = await env.sim(router_id)
    net = await env.net.state(router_id)
    return await read_targets(t, net, env.settings.load().known_devices), net


async def test_targets_merge_station_hint_and_known_device(env: FwEnv) -> None:
    env.settings.save(
        env.settings.load().model_copy(
            update={"known_devices": [KnownDevice(name="panel A", macs=[PANEL_WIFI, PANEL_ETH.upper()])]}
        )
    )
    targets, _ = await _targets(env, "ap1")
    wifi = next(x for x in targets if x.mac == PANEL_WIFI)
    assert (wifi.name, wifi.ip, wifi.via, wifi.device) == ("panel A", "192.168.1.30", "phy0-ap0", "phy0-ap0")
    eth = next(x for x in targets if x.mac == PANEL_ETH)  # remembered, though not seen now
    assert (eth.name, eth.ip, eth.via) == ("panel A", None, None)
    pc = next(x for x in targets if x.mac == PC_MAC)
    assert (pc.ip, pc.via, pc.device) == ("192.168.1.10", "wired", "eth0.1")


async def test_other_ip_fills_mac_from_hints_and_arp(env: FwEnv) -> None:
    targets, net = await _targets(env, "ap1")
    panel = resolve(TargetRef(None, "192.168.1.30"), targets, net, "AP1 · bench", "both")
    assert (panel.mac, panel.device) == (PANEL_WIFI, "phy0-ap0")
    other = resolve(TargetRef("02:00:00:00:00:01", "192.168.1.250"), targets, net, "AP1 · bench", "both")
    assert (other.mac, other.ip, other.via, other.device) == (
        "02:00:00:00:00:01",
        "192.168.1.250",
        None,
        "eth0.1",
    )


async def test_ip_and_mac_of_two_devices_refused(env: FwEnv) -> None:
    # the fault would take the IP's port and Wi-Fi link while matching the other device's MAC
    targets, net = await _targets(env, "ap1")
    text = rf"^192\.168\.1\.30 is {PANEL_WIFI}, not {PANEL_ETH}: enter a matching pair, or only one of them$"
    with pytest.raises(ValueError, match=text):
        resolve(TargetRef(PANEL_ETH, "192.168.1.30"), targets, net, "AP1 · bench", "both")
    same = resolve(TargetRef(PANEL_WIFI.upper(), "192.168.1.30"), targets, net, "AP1 · bench", "both")
    assert (same.mac, same.via) == (PANEL_WIFI, "phy0-ap0")


async def test_target_is_pc_refused(env: FwEnv) -> None:
    targets, net = await _targets(env, "ap1")
    text = r"^192\.168\.1\.10 is this PC \(the app's connection to AP1 · bench\)$"
    with pytest.raises(ValueError, match=text):
        resolve(TargetRef(None, "192.168.1.10"), targets, net, "AP1 · bench", "ip")
    with pytest.raises(ValueError, match=text):
        resolve(TargetRef(PC_MAC.upper(), None), targets, net, "AP1 · bench", "mac")


async def test_target_is_router_refused(env: FwEnv) -> None:
    targets, net = await _targets(env, "ap1")
    with pytest.raises(ValueError, match=r"^192\.168\.1\.1 is AP1 · bench itself$"):
        resolve(TargetRef(None, "192.168.1.1"), targets, net, "AP1 · bench", "ip")


async def test_router_mac_refused(env: FwEnv) -> None:
    # isolating the router's own MAC on its lan port would cut the app off with no way to clear it
    targets, net = await _targets(env, "ap1")
    macs = await router_macs(await env.sim("ap1"))
    assert "00:0c:43:76:20:17" in macs
    with pytest.raises(ValueError, match=r"^00:0c:43:76:20:17 is AP1 · bench itself$"):
        resolve(TargetRef("00:0C:43:76:20:17", None), targets, net, "AP1 · bench", "mac", macs)


async def test_missing_half_and_bad_text_refused(env: FwEnv) -> None:
    targets, net = await _targets(env, "ap1")
    with pytest.raises(ValueError, match=r"^No MAC known for 192\.168\.1\.77; enter one$"):
        resolve(TargetRef(None, "192.168.1.77"), targets, net, "AP1 · bench", "mac")
    with pytest.raises(ValueError, match="^No IPv4 address known for 02:00:00:00:00:01; enter one$"):
        resolve(TargetRef("02:00:00:00:00:01", None), targets, net, "AP1 · bench", "ip")
    with pytest.raises(ValueError, match="^panel is not a MAC address$"):
        resolve(TargetRef("panel", None), targets, net, "AP1 · bench", "mac")
    with pytest.raises(ValueError, match=r"^192\.168\.1\.300 is not an IPv4 address$"):
        resolve(TargetRef(None, "192.168.1.300"), targets, net, "AP1 · bench", "ip")
    with pytest.raises(ValueError, match="^Pick a target, or enter its IP or MAC$"):
        resolve(TargetRef(None, None), targets, net, "AP1 · bench", "ip")


async def test_wired_device_is_the_non_wireless_bridge_member(env: FwEnv) -> None:
    assert lan_wired_device(await env.net.state("ap2")) == "eth0.1"
