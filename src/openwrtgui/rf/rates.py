"""Which rates reach a station: minstrel's `rc_stats_csv` as rate rows (spec 7.3, v1.1b D7).

The kernel writes one line per supported rate and no header (`minstrel_ht_stats_csv_dump` in
`net/mac80211/rc80211_minstrel_ht_debugfs.c`, the same in Linux 5.15 and 6.6), 18 comma-separated fields:
mode, guard, streams, flags (`A B C D P S`, empty when none), rate name, index, airtime, max and average
throughput, average probability, retry count, last success, last attempts, total successes, total attempts,
ideal and sample packets, average A-MPDU length. Names are padded (`MCS7 `, ` 1.0M`), so fields are trimmed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openwrtgui.ifname import checked_ifname, checked_mac

FIELDS = 18
DEBUGFS = "/sys/kernel/debug/ieee80211"


class RateRow(BaseModel):
    """One rate minstrel tried, or the one it uses now (the field names are the UI's `RateRow`)."""

    model_config = ConfigDict(frozen=True)

    rate: str
    mode: str
    attempts: int
    success_pct: float
    in_use: bool


def rates_command(phy: str, ifname: str, mac: str) -> str:
    """The read the recorder sends too (`tools/record_fixtures.py`), after every name is checked."""
    return (
        f"cat {DEBUGFS}/{checked_ifname(phy)}/netdev:{checked_ifname(ifname)}/stations/{checked_mac(mac)}"
        "/rc_stats_csv"
    )


def _row(line: str) -> RateRow | None:
    fields = [f.strip() for f in line.split(",")]
    if len(fields) != FIELDS:
        return None
    mode, guard, _streams, flags, rate = fields[:5]
    try:
        successes, attempts = int(fields[13]), int(fields[14])
    except ValueError:
        return None
    in_use = "A" in flags  # minstrel's first-choice rate (max_tp_rate[0])
    if attempts <= 0 and not in_use:
        return None  # a supported rate minstrel never tried (ruling R1)
    return RateRow(
        rate=rate,
        mode=f"{mode} {guard}".strip(),
        attempts=max(attempts, 0),
        success_pct=round(100.0 * successes / attempts, 2) if attempts > 0 else 0.0,
        in_use=in_use,
    )


def parse_rc_stats_csv(text: str) -> list[RateRow]:
    """The rates minstrel tried at least once, plus the one in use, in the kernel's order. A line that is not
    the kernel's 18 fields, or whose counts are not numbers, is skipped."""
    return [row for line in text.splitlines() if line.strip() and (row := _row(line)) is not None]
