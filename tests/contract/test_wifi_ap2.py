"""The Wi-Fi parsers and the state reader against AP2's real answers (recorded parked, 2026-11-05)."""

import json
from datetime import datetime
from pathlib import Path

from openwrtgui.probe.describe import describe_router
from openwrtgui.transport.fake import ReplayTransport, load_commands
from openwrtgui.wifi.parse import parse_freqlist, parse_ht_mcs, parse_txpowerlist, parse_uci_show
from openwrtgui.wifi.state import read_wifi

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
PARKED = load_commands(AP2 / "wifi_parked.json")


def _json(command: str) -> dict[str, object]:
    return json.loads(PARKED[command].stdout)


def test_freqlist_is_channels_1_to_13_for_il() -> None:
    assert parse_freqlist(_json('ubus call iwinfo freqlist \'{"device":"radio0"}\'')) == tuple(range(1, 14))


def test_txpowerlist_tops_out_at_20_dbm() -> None:
    levels = parse_txpowerlist(_json('ubus call iwinfo txpowerlist \'{"device":"radio0"}\''))
    assert levels and max(levels) == 20


def test_ht_mcs_from_iw_phy_info() -> None:
    # AP2 (rt2800) lists "0-15, 32": two streams plus the 40 MHz duplicate MCS 32.
    assert parse_ht_mcs(PARKED["iw phy phy0 info"].stdout) == (*range(16), 32)


def test_uci_show_wireless_is_parked_il_with_the_key_hidden() -> None:
    uci = parse_uci_show(PARKED["uci -q show wireless"].stdout)
    assert uci["wireless.radio0.htmode"] == "HT40" and uci["wireless.radio0.country"] == "IL"
    assert uci["wireless.radio0.disabled"] == "1" and uci["wireless.radio0.legacy_rates"] == "1"
    assert uci["wireless.radio0.cell_density"] == "0"
    assert uci["wireless.default_radio0.key"] == "<hidden>"


def test_no_interface_while_parked() -> None:
    assert PARKED["iw dev"].stdout.strip() == ""


async def test_read_wifi_on_the_recordings_reads_ap2_parked() -> None:
    t = ReplayTransport({**load_commands(AP2 / "commands.json"), **PARKED})
    desc = await describe_router(t)
    state = await read_wifi(t, "ap2", desc, {}, lambda: datetime(2026, 11, 5, 8, 0))
    [radio] = state.radios
    assert radio.name == "radio0" and radio.band == "2g" and not radio.up and radio.disabled
    assert radio.channels.kind == "none" and radio.modes.kind == "auto" and radio.txpower.kind == "auto"
    assert radio.limits.channels == tuple(range(1, 14)) and radio.limits.max_htmode == "HT40"
    assert radio.limits.txpower_dbm[-1] == 20 and radio.limits.mcs == (*range(16), 32)
    assert radio.limits.phy == "phy0" and radio.limits.country == "IL" and radio.legacy_rates
    assert radio.writers == {
        "country": "dima_night",
        "cell_density": "dima_night",
        "legacy_rates": "dima_night",
    }
    assert radio.mask == "none" and radio.actual is None
    [ssid] = radio.ssids
    assert ssid.section == "default_radio0" and ssid.security == "wpa2" and ssid.key_set
    assert ssid.ifname is None
