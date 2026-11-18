"""Minstrel's rate statistics (`rc_stats_csv`) as rate rows (v1.1b Task 1, spec 7.3, D7).

The fixture `tests/fixtures/sim/rates/ht20.csv` was written from the kernel's own `printf`
(`minstrel_ht_stats_csv_dump`, identical in Linux 5.15 and 6.6), not recorded from a router: no AP2 recording
of `rc_stats_csv` exists yet (plan ruling R3). The AP2 window pins the real answer with a contract test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.ifname import checked_mac
from openwrtgui.rf.rates import RateRow, parse_rc_stats_csv, rates_command

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sim" / "rates" / "ht20.csv"
TAIL = "4200,310,1.0"


def _line(mode: str, guard: str, flags: str, rate: str, success: int, attempts: int) -> str:
    return f"{mode},{guard},1,{flags},{rate},7,166,41.6,33.3,80.0,4,2,2,{success},{attempts},{TAIL}"


def test_rows_are_the_rates_minstrel_tried_and_the_one_in_use() -> None:
    rows = parse_rc_stats_csv(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 9
    assert all(r.attempts > 0 for r in rows if not r.in_use)
    in_use = [r for r in rows if r.in_use]
    assert len(in_use) == 1
    assert in_use[0].model_dump() == {
        "rate": "MCS15",
        "mode": "HT20 LGI",
        "attempts": 900,
        "success_pct": pytest.approx(94.44, abs=0.01),
        "in_use": True,
    }
    assert isinstance(in_use[0], RateRow)


def test_cck_rows_keep_their_preamble_in_the_mode() -> None:
    rows = parse_rc_stats_csv(_line("CCK", "SP", "", "11.0M", 1, 1) + "\n")
    assert [(r.mode, r.rate) for r in rows] == [("CCK SP", "11.0M")]


def test_ofdm_has_no_guard() -> None:
    rows = parse_rc_stats_csv(_line("OFDM", "", "", " 6.0M", 3, 4) + "\n")
    assert [(r.mode, r.rate, r.attempts, r.success_pct) for r in rows] == [("OFDM", "6.0M", 4, 75.0)]


def test_a_line_with_the_wrong_field_count_is_skipped() -> None:
    good = _line("HT20", "LGI", "A", "MCS7 ", 20, 25)
    short = good.rsplit(",", 1)[0]  # 17 fields
    text = "\n".join([short, "garbage", good, "HT20,LGI,1,,MCS1 ,x,1,1,1,1,1,1,1,y,z,1,1,1.0"]) + "\n"
    rows = parse_rc_stats_csv(text)
    assert [(r.rate, r.attempts, r.in_use) for r in rows] == [("MCS7", 25, True)]


@pytest.mark.parametrize("text", ["", "\n"])
def test_nothing_tried_and_empty_answers_give_no_rows(text: str) -> None:
    assert parse_rc_stats_csv(text) == []


def test_zero_attempts_in_use_is_zero_percent() -> None:
    rows = parse_rc_stats_csv(_line("HT20", "LGI", "AP", "MCS0 ", 0, 0) + "\n")
    assert [(r.rate, r.attempts, r.success_pct, r.in_use) for r in rows] == [("MCS0", 0, 0.0, True)]


def test_rates_command_is_the_recorder_command() -> None:
    cmd = rates_command("phy0", "phy0-ap0", "f4:12:fa:f3:57:68")
    assert (
        cmd == "cat /sys/kernel/debug/ieee80211/phy0/netdev:phy0-ap0/stations/f4:12:fa:f3:57:68/rc_stats_csv"
    )
    assert is_read_only_command(cmd)


def test_rates_command_checks_its_names() -> None:
    with pytest.raises(ValueError):
        rates_command("phy0;reboot", "phy0-ap0", "f4:12:fa:f3:57:68")
    with pytest.raises(ValueError):
        rates_command("phy0", "phy0-ap0", "../../x")


def test_checked_mac() -> None:
    assert checked_mac("F4:12:FA:F3:57:68") == "f4:12:fa:f3:57:68"
    for bad in ("../../x", "f4:12:fa:f3:57:68; reboot", "", "f4-12-fa-f3-57-68"):
        with pytest.raises(ValueError, match="Not a station MAC"):
            checked_mac(bad)
