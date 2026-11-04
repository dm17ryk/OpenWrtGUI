from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.simulator import SimConnector
from openwrtgui.simwifi import SimWifi
from openwrtgui.transport.fake import ReplayTransport, SimState
from openwrtgui.wifi.compile import apply_script, compile_channels, compile_modes
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioLimits
from openwrtgui.wifi.parse import parse_beacon_rates, parse_iw_dev_info, parse_uci_show

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"
LIMITS = RadioLimits(
    "2g", "phy0", "HT40", tuple(range(1, 14)), tuple(range(21)), tuple(range(16)), "IL", True
)
BEACON = (
    "timeout 5 tcpdump -i owgmon0 -e -n -c 5 -l 'type mgt subtype beacon and wlan addr2 02:00:00:00:00:02'"
)


def _ap2() -> ReplayTransport:
    text = (SIM_DIR / "wifi" / "ap2.uci").read_text(encoding="utf-8")
    return ReplayTransport({}, state=SimState(wifi=SimWifi(text, bssid="02:00:00:00:00:02")))


async def _apply(t: ReplayTransport, modes: ModeSelection, channels: ChannelSelection) -> None:
    ops = compile_modes("radio0", modes, LIMITS) + compile_channels("radio0", channels, LIMITS)
    result = await t.run(apply_script("radio0", ops), timeout=60)
    assert result.ok, result.stderr


async def test_apply_script_changes_state_and_reload_recreates_interface() -> None:
    t = _ap2()
    status = json.loads((await t.run("ubus call network.wireless status")).stdout)
    assert status["radio0"]["up"] is False and status["radio0"]["interfaces"] == []
    assert (await t.run("iw dev phy0-ap0 info")).exit_status != 0
    await _apply(t, ModeSelection.of("n20"), ChannelSelection.of(6))
    status = json.loads((await t.run("ubus call network.wireless status")).stdout)
    radio = status["radio0"]
    assert radio["up"] is True and radio["pending"] is False
    assert radio["config"]["htmode"] == "HT20" and radio["interfaces"][0]["ifname"] == "phy0-ap0"
    first = parse_iw_dev_info((await t.run("iw dev phy0-ap0 info")).stdout)
    assert (first.channel, first.width_mhz, first.no_ht) == (6, 20, False)
    assert (await t.run("iw dev phy0-ap0 set bitrates legacy-2.4 6 ht-mcs-2.4 0 1")).ok
    await t.run("wifi down radio0; wifi up radio0")
    second = parse_iw_dev_info((await t.run("iw dev phy0-ap0 info")).stdout)
    assert second.ifindex is not None and first.ifindex is not None and second.ifindex > first.ifindex
    shown = parse_uci_show((await t.run("uci -q show wireless")).stdout)
    assert shown["wireless.radio0.channel"] == "6" and shown["wireless.radio0.disabled"] == "0"


async def test_uncommitted_changes_are_not_shown() -> None:
    t = _ap2()
    await t.run("uci set wireless.radio0.channel='11'")
    assert parse_uci_show((await t.run("uci -q show wireless")).stdout)["wireless.radio0.channel"] == "1"


async def test_beacon_rate_follows_basic_rate() -> None:
    t = _ap2()
    await _apply(t, ModeSelection.of("b", "n20"), ChannelSelection.of(1))
    assert (await t.run("iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up")).ok
    assert set(parse_beacon_rates((await t.run(BEACON, timeout=10)).stdout)) == {1.0}
    assert (await t.run("ip link del owgmon0")).ok
    await _apply(t, ModeSelection.of("n20"), ChannelSelection.of(1))
    await t.run("iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up")
    rates = parse_beacon_rates((await t.run(BEACON, timeout=10)).stdout)
    assert len(rates) == 5 and set(rates) == {6.0}


async def test_no_beacons_without_the_monitor_interface() -> None:
    t = _ap2()
    await _apply(t, ModeSelection.of("g"), ChannelSelection.of(1))
    assert parse_beacon_rates((await t.run(BEACON, timeout=10)).stdout) == []


async def test_station_present_only_while_up_and_del_client_removes_it() -> None:
    t = _ap2()
    assoc = 'ubus call iwinfo assoclist \'{"device":"phy0-ap0"}\''
    assert (await t.run(assoc)).exit_status != 0
    await _apply(t, ModeSelection.auto(), ChannelSelection.of(6))
    assert len(json.loads((await t.run(assoc)).stdout)["results"]) == 1
    assert "Station f4:12:fa:f3:57:68 (on phy0-ap0)" in (await t.run("iw dev phy0-ap0 station dump")).stdout
    ban = (
        "ubus call hostapd.phy0-ap0 del_client "
        '\'{"addr":"f4:12:fa:f3:57:68","ban_time":60000,"deauth":true,"reason":3}\''
    )
    assert (await t.run(ban)).ok
    assert json.loads((await t.run(assoc)).stdout)["results"] == []
    hints = json.loads((await t.run("ubus call luci-rpc getHostHints")).stdout)
    assert hints["F4:12:FA:F3:57:68"]["name"] == "panel"


async def test_sectioned_rf_command_is_answered_part_by_part() -> None:
    t = _ap2()
    await _apply(t, ModeSelection.auto(), ChannelSelection.of(6))
    out = (
        await t.run(
            "echo ===STA; iw dev phy0-ap0 station dump; echo ===SURVEY; iw dev phy0-ap0 survey dump; "
            "echo ===ACK; cat /sys/kernel/debug/ieee80211/phy0/statistics/dot11ACKFailureCount 2>/dev/null; "
            "echo ===INFO; iw dev phy0-ap0 info"
        )
    ).stdout
    assert out.index("===STA") < out.index("Station ") < out.index("===SURVEY") < out.index("[in use]")
    assert "===INFO\nInterface phy0-ap0" in out


async def test_sessions_are_simulated() -> None:
    t = _ap2()
    created = json.loads((await t.run("ubus call session create '{\"timeout\":300}'")).stdout)
    assert created["ubus_rpc_session"].startswith("sim-")
    assert (
        await t.run(f'ubus call session destroy \'{{"ubus_rpc_session":"{created["ubus_rpc_session"]}"}}\'')
    ).ok


async def test_unknown_command_falls_back_to_recordings() -> None:
    connector = SimConnector(SIM_DIR)
    t = await connector.connect("192.168.1.2", 22, password=None, key_paths=[Path("k")])
    assert '"model"' in (await t.run("cat /etc/board.json")).stdout
    status = json.loads((await t.run("ubus call network.wireless status")).stdout)
    assert status["radio0"]["config"]["country"] == "IL"


async def test_ap1_matches_its_recorded_overlay() -> None:
    connector = SimConnector(SIM_DIR)
    t = await connector.connect("192.168.1.1", 22, password=None, key_paths=[Path("k")])
    radio = json.loads((await t.run("ubus call network.wireless status")).stdout)["radio0"]
    assert radio["up"] is True and radio["config"]["channel"] == "1" and radio["config"]["htmode"] == "HT20"
    assert radio["config"]["txpower"] == 20 and radio["interfaces"][0]["config"]["ssid"] == "OpenWrt"
    info = json.loads((await t.run('ubus call iwinfo info \'{"device":"phy0-ap0"}\'')).stdout)
    assert info["channel"] == 1 and info["txpower"] == 20


def test_sim_fixtures_hide_keys() -> None:
    for path in (SIM_DIR / "wifi").glob("*.uci"):
        for path_key, value in parse_uci_show(path.read_text(encoding="utf-8")).items():
            if path_key.endswith(".key"):
                assert value == "<hidden>", path
