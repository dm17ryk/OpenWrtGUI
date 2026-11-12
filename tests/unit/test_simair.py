"""The simulator's air (v0.7 plan Task 7): scans, every channel's survey, frame windows, get_clients."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.rf.air import FRAME_WINDOW, MONITOR_FLAGS, SCAN_DEL, scan_add, scan_command, survey_command
from openwrtgui.rf.frames import summarize
from openwrtgui.rf.parse import current_survey, parse_survey, split_sections
from openwrtgui.rf.sample import rf_command
from openwrtgui.rf.scan import parse_scan
from openwrtgui.simwifi import STATION_MAC, SimWifi
from openwrtgui.transport.fake import ReplayTransport, SimState
from openwrtgui.wifi.compile import apply_script, compile_channels, compile_modes, reload_command
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioLimits
from openwrtgui.wifi.monitor import add_command

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"
LIMITS = RadioLimits(
    "2g", "phy0", "HT40", tuple(range(1, 14)), tuple(range(21)), tuple(range(16)), "IL", True
)
BSSID = "02:00:00:00:00:02"


def _ap2() -> ReplayTransport:
    text = (SIM_DIR / "wifi" / "ap2.uci").read_text(encoding="utf-8")
    return ReplayTransport({}, state=SimState(wifi=SimWifi(text, bssid=BSSID)))


async def _on_air(t: ReplayTransport, channel: int = 6) -> None:
    ops = compile_modes("radio0", ModeSelection.of("n20"), LIMITS)
    ops += compile_channels("radio0", ChannelSelection.of(channel), LIMITS)
    for command in (apply_script("radio0", ops), reload_command("radio0")):
        assert (await t.run(command, timeout=60)).ok


async def test_parked_scan_via_owgscan0() -> None:
    t = _ap2()
    assert (await t.run(scan_add("phy0"))).ok
    before = parse_survey((await t.run(survey_command("owgscan0"))).stdout)
    scanned = await t.run(scan_command("owgscan0", on_ap=False))
    after = parse_survey((await t.run(survey_command("owgscan0"))).stdout)
    networks = parse_scan(scanned.stdout)
    assert len(networks) == 6 and not any(b.own for b in networks)
    assert {b.ssid for b in networks} >= {"net-01", None, "net-04 café"}
    assert len(before) == len(after) == 13
    pairs = zip(after, before, strict=True)
    assert all(a.active_ms and b.active_ms and a.active_ms > b.active_ms for a, b in pairs)
    assert (await t.run(SCAN_DEL)).ok
    assert not (await t.run(SCAN_DEL)).ok  # gone


async def test_ap_scan_needs_ap_force() -> None:
    t = _ap2()
    await _on_air(t)
    refused = await t.run(scan_command("phy0-ap0", on_ap=False))
    assert refused.exit_status == 240 and "Device or resource busy" in refused.stderr
    heard = parse_scan((await t.run(scan_command("phy0-ap0", on_ap=True))).stdout, own={BSSID})
    assert len(heard) == 7 and [b.channel for b in heard if b.own] == [6]


async def test_survey_lists_every_channel_and_keeps_rf_live() -> None:
    t = _ap2()
    await _on_air(t, 6)
    # the RF sampler's compound read (its station dump is the sim's tick) still goes to SimWifi
    sections = split_sections((await t.run(rf_command("phy0-ap0", "phy0"))).stdout)
    sampler = parse_survey(sections["SURVEY"])
    every = parse_survey((await t.run(survey_command("phy0-ap0"))).stdout)
    assert [s.freq_mhz for s in every] == [2407 + 5 * c for c in range(1, 14)]
    own = current_survey(every, 2437)  # the same counters for the own channel
    assert own is not None and (own.active_ms, own.busy_ms) == (sampler[0].active_ms, sampler[0].busy_ms)


async def test_frame_window_summarizes() -> None:
    t = _ap2()
    await _on_air(t)
    assert (await t.run(add_command("phy0", clear_leftover=True))).ok
    assert (await t.run(MONITOR_FLAGS)).ok
    window = await t.run(FRAME_WINDOW)
    assert window.exit_status == 124
    summary = summarize(window.stdout, window.stderr, {BSSID}, 3.0)
    assert (summary.rx.frames, summary.tx.frames, summary.rx.retries, summary.bad_fcs) == (40, 60, 4, 2)
    assert summary.dropped == 0 and sum(summary.rx.signal_hist.values()) == 40


async def test_reload_drops_the_monitor() -> None:
    t = _ap2()
    await _on_air(t)
    assert (await t.run(add_command("phy0", clear_leftover=True))).ok
    assert (await t.run("iw dev owgmon0 info")).ok
    assert (await t.run(reload_command("radio0"), timeout=60)).ok
    assert not (await t.run("iw dev owgmon0 info")).ok
    assert not (await t.run(MONITOR_FLAGS)).ok


async def test_get_clients_while_up() -> None:
    t = _ap2()
    await _on_air(t)
    clients = json.loads((await t.run("ubus call hostapd.phy0-ap0 get_clients")).stdout)["clients"]
    assert clients[STATION_MAC] == {"auth": True, "assoc": True, "authorized": True}
