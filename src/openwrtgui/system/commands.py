"""The exact commands the System screen sends (v0.6b plan, "Rules"). Reads are LuCI's own reads on this image
(D2); every value put into a write matches a `re.fullmatch` rule first and is shell-quoted."""

from __future__ import annotations

from typing import Literal

BOARD = "ubus call system board"
INFO = "ubus call system info"
UCI_SYSTEM = "uci -X show system"
RC_LIST = "ubus call rc list"
TIMEZONES = "ubus call luci getTimezones"
TOP = "top -bn1"
DMESG = "dmesg -r"
RC_LOCAL = "cat /etc/rc.local"
CRONTAB = "cat /etc/crontabs/root"
TZ_FILE = "cat /tmp/TZ"
# one exec for the live charts (D3): load, bytes per interface, the connection count
LIVE = "cat /proc/loadavg /proc/net/dev /proc/sys/net/netfilter/nf_conntrack_count"
CONNTRACK = "head -n 500 /proc/net/nf_conntrack"  # AP2 has ~7 MB free RAM: the table is capped
BACKUP = "sysupgrade -b -"  # the archive on stdout (D9): it holds secrets, never recorded or logged
BACKUP_SIZE = "sysupgrade -b - | wc -c"  # what the recorder keeps of it

LogLength = Literal[100, 500, 2000]
LOG_LENGTHS: tuple[LogLength, ...] = (100, 500, 2000)


def logread(lines: LogLength) -> str:
    if lines not in LOG_LENGTHS:
        raise ValueError(f"The system log is read in {', '.join(map(str, LOG_LENGTHS))} lines")
    return f"logread -l {lines}"
