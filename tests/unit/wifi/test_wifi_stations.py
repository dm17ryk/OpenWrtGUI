from __future__ import annotations

import pytest

from conftest import WifiEnv
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.wifi.stations import Station, del_client_command, mode_label

MAC = "f4:12:fa:f3:57:68"


async def test_stations_with_names_from_host_hints(env: WifiEnv) -> None:
    assert await env.service.stations("ap1") == [
        Station(
            mac=MAC,
            ifname="phy0-ap0",
            ssid="OpenWrt",
            name="panel",
            ip="192.168.1.30",
            signal_dbm=-52,
            tx_mbps=65.0,
            tx_mcs=7,
            rx_mbps=54.0,
            mode="802.11n 20",
            connected_s=11520,
            inactive_ms=40,
        )
    ]


async def test_parked_radio_has_no_stations(env: WifiEnv) -> None:
    assert await env.service.stations("ap2") == []


def test_mode_labels() -> None:
    assert mode_label({"rate": 150000, "mcs": 7, "ht": True, "40mhz": True}) == "802.11n 40"
    assert mode_label({"rate": 65000, "mcs": 7, "ht": True, "40mhz": False}) == "802.11n 20"
    assert mode_label({"rate": 11000, "ht": False}) == "802.11b"
    assert mode_label({"rate": 5500}) == "802.11b"
    assert mode_label({"rate": 54000, "ht": False}) == "802.11g"
    assert mode_label({}) == "unknown"


def test_del_client_command() -> None:
    assert del_client_command("phy0-ap0", MAC, 0) == (
        "ubus call hostapd.phy0-ap0 del_client "
        '\'{"addr":"f4:12:fa:f3:57:68","ban_time":0,"deauth":true,"reason":3}\''
    )


async def test_deauth_and_block_commands(env: WifiEnv) -> None:
    assert (await env.service.deauth("ap1", MAC.upper())).ok
    assert env.audit_lines() == [(del_client_command("phy0-ap0", MAC, 0), "user")]
    assert await env.service.stations("ap1") == []  # gone for a few samples, then back
    for _ in range(3):
        await env.service.stations("ap1")
    assert (await env.service.block("ap1", MAC, 60)).ok
    assert env.audit_lines()[-1] == (del_client_command("phy0-ap0", MAC, 60000), "user")


async def test_block_range_and_unknown_station_refused(env: WifiEnv) -> None:
    with pytest.raises(ValueError, match="Block for 10 to 3600 seconds"):
        await env.service.block("ap1", MAC, 5)
    with pytest.raises(ValueError, match="Block for 10 to 3600 seconds"):
        await env.service.block("ap1", MAC, 3601)
    with pytest.raises(ValueError, match="aa:bb:cc:dd:ee:ff is not connected to AP1 · bench"):
        await env.service.deauth("ap1", "aa:bb:cc:dd:ee:ff")


async def test_station_actions_refused_while_guard_live(env: WifiEnv) -> None:
    env.go_live()
    with pytest.raises(GuardLocked):
        await env.service.deauth("ap1", MAC)
    assert env.audit.query() == []
    assert len(await env.service.stations("ap1")) == 1  # reading still works
