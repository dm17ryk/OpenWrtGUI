"""The exact commands the System screen sends (v0.6b plan, "Rules"). Reads are LuCI's own reads on this image
(D2); every value put into a write matches a `re.fullmatch` rule first and is shell-quoted."""

from __future__ import annotations

import re
from typing import Literal

from openwrtgui.uci import shell_quote

HOSTNAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?")  # one RFC 1123 label
NTP_SERVER = re.compile(r"(?!-)[A-Za-z0-9.:-]{1,253}")  # a host name or an address, never an option
TARGET = NTP_SERVER
SERVICE = re.compile(r"(?!\.)[A-Za-z0-9._-]{1,64}")
# the Services tab offers the first five; `reload` is what a System settings apply sends (D5)
InitAction = Literal["start", "stop", "restart", "enable", "disable", "reload"]
INIT_ACTIONS: tuple[InitAction, ...] = ("start", "stop", "restart", "enable", "disable", "reload")
ServiceAction = Literal["start", "stop", "restart", "enable", "disable"]
SERVICE_ACTIONS: tuple[ServiceAction, ...] = ("start", "stop", "restart", "enable", "disable")
FilePath = Literal["/etc/rc.local", "/etc/crontabs/root"]
FILES: tuple[FilePath, ...] = ("/etc/rc.local", "/etc/crontabs/root")
MAX_FILE = 8 * 1024
DIAG_LIMIT_S = 25  # D4: a diagnostic never runs longer, whatever the network does

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

# v0.6c reads (Access, LEDs, mount points, the files kept in a backup): LuCI's own on this image
UCI_DROPBEAR = "uci -X show dropbear"
UCI_UHTTPD = "uci -X show uhttpd"
UCI_RPCD = "uci -X show rpcd"
AUTHORIZED_KEYS = "/etc/dropbear/authorized_keys"
KEYS_READ = f"cat {AUTHORIZED_KEYS}"  # public keys only
APK_KEYS = "ls -1 /etc/apk/keys"
OPKG_KEYS = "ls -1 /etc/opkg/keys"
LEDS = "ubus call luci getLEDs"
NET_DEVICES = "ls -1 /sys/class/net"
MOUNTS = "cat /proc/mounts"
DF = "df -k"
HAS_BLOCK = "test -x /sbin/block"  # LuCI shows Mount points only with block-mount (D8)
KEPT = "cat /etc/sysupgrade.conf"
BACKUP_LIST = "sysupgrade -l"
LISTENERS = "cat /proc/net/tcp /proc/net/tcp6"
# A digest of root's shadow field (D2): proves a password change without the hash leaving the router.
# Derived from a secret: compared live, never recorded, logged or shown.
PASSWORD_DIGEST = """awk -F: '$1=="root"{print $2}' /etc/shadow | sha256sum"""
# the digest of a lone newline: root has no password
EMPTY_DIGEST = "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b"

LogLength = Literal[100, 500, 2000]
LOG_LENGTHS: tuple[LogLength, ...] = (100, 500, 2000)


def logread(lines: LogLength) -> str:
    if lines not in LOG_LENGTHS:
        raise ValueError(f"The system log is read in {', '.join(map(str, LOG_LENGTHS))} lines")
    return f"logread -l {lines}"


def _checked(rule: re.Pattern[str], value: str, what: str) -> str:
    if not rule.fullmatch(value):
        raise ValueError(f"{value!r} is not {what}")
    return value


def init(name: str, action: InitAction) -> str:
    if action not in INIT_ACTIONS:
        raise ValueError(f"{action!r} is not one of {', '.join(INIT_ACTIONS)}")
    return f"/etc/init.d/{_checked(SERVICE, name, 'a service name')} {action}"


def _diag(program: str, target: str) -> str:
    host = _checked(TARGET, target, "a host name or an address")
    return f"timeout -s KILL {DIAG_LIMIT_S} {program} {shell_quote(host)}"


def ping(target: str) -> str:
    return _diag("ping -c 4 -W 2", target)


def traceroute(target: str) -> str:
    return _diag("traceroute -m 15 -w 2 -q 1 -n", target)


def nslookup(target: str) -> str:
    return _diag("nslookup", target)


def write_file(path: FilePath, text: str) -> str:
    """The whole file as one heredoc (D7): what the preview shows is what the router gets."""
    from openwrtgui.fw.tables import heredoc  # here: fw imports net.apply, which reaches the guard

    if path not in FILES:
        raise ValueError(f"The System screen writes only {', '.join(FILES)}")
    if len(text.encode()) > MAX_FILE:
        raise ValueError("The file is at most 8 KiB")
    head = f"cat > {path}"
    if path == "/etc/crontabs/root":
        head = f"mkdir -p /etc/crontabs && {head}"
    return heredoc(head, text.rstrip("\n"))
