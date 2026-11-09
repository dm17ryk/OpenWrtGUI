"""system/parse.py on the shapes AP2's OpenWrt and busybox print (until the HW-1 recording replaces them)."""

from __future__ import annotations

import json

from openwrtgui.system.parse import (
    parse_board,
    parse_conntrack,
    parse_dmesg,
    parse_info,
    parse_live,
    parse_logread,
    parse_rc_list,
    parse_timezones,
    parse_top,
    rates,
)

BOARD = {
    "kernel": "6.18.41",
    "hostname": "OpenWrt",
    "system": "MT7620N  ver:2 eco:6",
    "model": "D-Link DWR-921 C3 (U-Boot)",
    "board_name": "dlink,dwr-921-c3-uboot",
    "rootfs_type": "squashfs",
    "release": {
        "distribution": "OpenWrt",
        "revision": "r35692-b8bffeefdf",
        "description": "OpenWrt SNAPSHOT",
    },
}
INFO = {
    "localtime": 1793717401,
    "uptime": 1786118,
    "load": [10496, 2176, 704],
    "memory": {"total": 56426496, "free": 11665408, "shared": 1896448, "buffered": 0, "available": 7663616},
    "root": {"total": 1408, "free": 1004, "used": 404, "avail": 1004},
    "tmp": {"total": 27552, "free": 27012, "used": 540, "avail": 27012},
    "swap": {"total": 0, "free": 0},
}
TOP = """Mem: 26388K used, 28716K free, 1852K shrd, 2108K buff, 15216K cached
CPU:   0% usr   9% sys   0% nic  90% idle   0% io   0% irq   0% sirq
Load average: 0.16 0.03 0.01 2/52 25700
  PID  PPID USER     STAT   RSS %RSS %CPU COMMAND
 1582     1 root     S     3000   5%   0% /sbin/netifd -l 2
25700 25699 root     R     1452   3%   9% top -bn1
 1517  1513 network  S    10.2m  19%   1% /usr/sbin/wpa_supplicant -n -s -g /var/run/wpa_supplicant/global
    2     0 root     SW       0   0%   0% [kthreadd]
"""
# /proc/net/dev with its columns closed up (the parser splits on whitespace)
DEV = """Inter-|   Receive                                         |  Transmit
 face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls
    lo: 1000 10 0 0 0 0 0 0 1000 10 0 0 0 0 0 0
  eth0: 5000000 40000 0 0 0 0 0 12 9000000 50000 0 0 0 0 0 0
 wwan0: 12173 37 0 0 0 0 0 0 257532310 739945 0 0 0 0 0 0
"""


def test_board_and_info() -> None:
    board = parse_board(json.dumps(BOARD))
    assert board is not None
    assert (board.model, board.board_name, board.kernel, board.hostname) == (
        "D-Link DWR-921 C3 (U-Boot)",
        "dlink,dwr-921-c3-uboot",
        "6.18.41",
        "OpenWrt",
    )
    assert (board.release, board.revision) == ("OpenWrt SNAPSHOT", "r35692-b8bffeefdf")
    info = parse_info(json.dumps(INFO))
    assert info is not None
    assert (info.localtime, info.uptime_s) == (1793717401, 1786118)
    assert info.load == (0.16, 0.03, 0.01)  # /65536, two decimals
    assert (info.memory_total, info.memory_available) == (56426496, 7663616)
    assert (info.root_total_kib, info.root_free_kib, info.tmp_total_kib, info.tmp_free_kib) == (
        1408,
        1004,
        27552,
        27012,
    )
    assert parse_board("not json") is None and parse_info("{}") is not None


def test_logread_line() -> None:
    text = (
        "Sun Nov  8 15:29:02 2026 authpriv.info dropbear[24543]: Child connection from 192.168.1.10:53498\n"
        "Sun Nov  8 15:29:10 2026 daemon.notice netifd: radio0 (24611): wifi-scripts: Tearing down phy0\n"
        "Mon Nov  9 01:02:03 2026 kern.warn kernel: [   12.345] something odd\n"
        "a line that is not a log line\n"
    )
    lines = parse_logread(text)
    assert len(lines) == 4
    first = lines[0]
    assert (first.time, first.facility, first.level, first.source, first.pid) == (
        "Sun Nov  8 15:29:02 2026",
        "authpriv",
        "info",
        "dropbear",
        24543,
    )
    assert first.message == "Child connection from 192.168.1.10:53498"
    assert (lines[1].source, lines[1].pid, lines[1].message) == (
        "netifd",
        None,
        "radio0 (24611): wifi-scripts: Tearing down phy0",
    )
    assert (lines[2].facility, lines[2].level, lines[2].source) == ("kern", "warn", "kernel")
    assert (lines[3].level, lines[3].message) == (None, "a line that is not a log line")  # kept, not dropped


def test_dmesg_raw_line() -> None:
    lines = parse_dmesg("<6>[    0.000000] Linux version 6.18.41\n<4>[  12.500000] rt2800: odd\nplain\n")
    assert [(k.level, k.seconds, k.message) for k in lines] == [
        (6, 0.0, "Linux version 6.18.41"),
        (4, 12.5, "rt2800: odd"),
        (None, None, "plain"),
    ]


def test_top_rows_and_cpu_line() -> None:
    rows, cpu, column = parse_top(TOP)
    assert cpu == "0% usr   9% sys   0% nic  90% idle   0% io   0% irq   0% sirq"
    assert [r.pid for r in rows] == [25700, 1517, 1582, 2]  # by CPU, then by VSZ
    top = rows[0]
    assert (top.ppid, top.user, top.state, top.mem_kib, top.mem_pct, top.cpu_pct, top.command) == (
        25699,
        "root",
        "R",
        1452,
        3.0,
        9.0,
        "top -bn1",
    )
    assert column == "RSS"  # this busybox build shows resident memory, not VSZ (AP2, 2026-11-09)
    assert rows[1].mem_kib == 10445  # 10.2m = 10444.8 KiB
    assert parse_top("") == ([], None, None)


def test_rc_list() -> None:
    text = json.dumps(
        {
            "cron": {"start": 50, "enabled": True, "running": True},
            "dnsmasq": {"start": 19, "stop": 10, "enabled": True, "running": True},
            "odhcpd": {"start": 35, "stop": 85, "enabled": False, "running": False},
        }
    )
    services = parse_rc_list(text)
    assert [(r.name, r.start, r.stop, r.enabled, r.running) for r in services] == [
        ("cron", 50, None, True, True),
        ("dnsmasq", 19, 10, True, True),
        ("odhcpd", 35, 85, False, False),
    ]
    assert parse_rc_list("Command failed: Not found") == []


def test_timezones() -> None:
    text = json.dumps(
        {
            "UTC": {"tzstring": "UTC0", "active": True},
            "Asia/Jerusalem": {"tzstring": "IST-2IDT,M3.4.4/26,M10.5.0"},
        }
    )
    assert parse_timezones(text) == {"UTC": "UTC0", "Asia/Jerusalem": "IST-2IDT,M3.4.4/26,M10.5.0"}
    assert parse_timezones("") == {}


def test_live_sample_and_rates() -> None:
    first = parse_live(f"0.16 0.03 0.01 2/52 25700\n{DEV}42\n", 100.0)
    assert (first.load1, first.load5, first.load15, first.connections) == (0.16, 0.03, 0.01, 42)
    assert first.interfaces["eth0"] == (5000000, 9000000) and first.interfaces["wwan0"] == (12173, 257532310)
    assert "lo" not in first.interfaces
    later_dev = DEV.replace("5000000", "5030000").replace("9000000", "9090000")
    second = parse_live(f"0.20 0.04 0.01 2/52 25701\n{later_dev}40\n", 103.0)
    assert rates(first, second)["eth0"] == (10000.0, 30000.0)  # bytes per second over 3 s
    no_count = parse_live(f"0.16 0.03 0.01 2/52 25700\n{DEV}", 100.0)  # nf_conntrack not loaded
    assert no_count.connections is None and no_count.interfaces


def test_conntrack_line() -> None:
    text = (
        "ipv4     2 tcp      6 7440 ESTABLISHED src=192.168.1.10 dst=192.168.1.2 sport=53498 dport=22 "
        "packets=40 bytes=4000 src=192.168.1.2 dst=192.168.1.10 sport=22 dport=53498 packets=30 bytes=6000 "
        "[ASSURED] mark=0 use=2\n"
        "ipv4     2 udp      17 29 src=10.0.0.1 dst=8.8.8.8 sport=5353 dport=53 packets=1 bytes=60 "
        "[UNREPLIED] src=8.8.8.8 dst=10.0.0.1 sport=53 dport=5353 packets=0 bytes=0 mark=0 use=2\n"
    )
    conns = parse_conntrack(text)
    assert [(c.proto, c.src, c.dst, c.sport, c.dport, c.state, c.bytes) for c in conns] == [
        ("tcp", "192.168.1.10", "192.168.1.2", 53498, 22, "ESTABLISHED", 10000),
        ("udp", "10.0.0.1", "8.8.8.8", 5353, 53, None, 60),
    ]
