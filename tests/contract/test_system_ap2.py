"""AP2's recorded System reads (tests/fixtures/ap2/system.json, 2026-11-09) against the System parsers. The
recording found: busybox top shows RSS (not VSZ), cron is enabled but not running while no crontab exists,
and the router's time zone list has no "UTC" although AP2 is set to it (LuCI adds UTC itself)."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.system import commands as s
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
)
from openwrtgui.uci import parse_uci_show

RECORDING: dict[str, dict[str, object]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "system.json").read_text(encoding="utf-8")
)


def _out(command: str) -> str:
    entry = RECORDING[command]
    assert entry["exit"] == 0, (command, entry.get("stderr"))
    return str(entry["stdout"])


def test_overview_parses() -> None:
    board = parse_board(_out(s.BOARD))
    assert board is not None
    assert (board.model, board.board_name, board.kernel, board.hostname) == (
        "D-Link DWR-921 C3 (U-Boot)",
        "dlink,dwr-921-c3-uboot",
        "6.18.41",
        "OpenWrt",
    )
    assert board.release == "OpenWrt SNAPSHOT r35692-b8bffeefdf" and board.revision == "r35692-b8bffeefdf"
    info = parse_info(_out(s.INFO))
    assert info is not None and info.uptime_s and info.load and info.memory_total == 56426496
    assert info.memory_available and info.root_total_kib and info.tmp_free_kib


def test_system_config_reads() -> None:
    shown = parse_uci_show(_out(s.UCI_SYSTEM))
    assert shown["system.cfg01e48a"] == "system"
    assert (shown["system.cfg01e48a.hostname"], shown["system.cfg01e48a.zonename"]) == ("OpenWrt", "UTC")
    assert shown["system.cfg01e48a.timezone"] == "GMT0" and shown["system.cfg01e48a.log_size"] == "128"
    assert shown["system.ntp.enabled"] == "1" and shown["system.ntp.enable_server"] == "0"
    assert len(shown["system.ntp.server"].split()) == 4
    assert _out(s.TZ_FILE) == "GMT0\n"


def test_logread_parses() -> None:
    lines = parse_logread(_out(s.logread(100)))
    assert len(lines) == 100
    assert all(line.level is not None for line in lines)  # every recorded line is logd's own format


def test_dmesg_parses() -> None:
    lines = parse_dmesg(_out(s.DMESG))
    assert len(lines) > 100
    assert all(line.level is not None and line.seconds is not None for line in lines)


def test_top_parses() -> None:
    rows, cpu, column = parse_top(_out(s.TOP))
    assert column == "RSS" and cpu is not None and "idle" in cpu
    assert len(rows) > 20
    assert any(r.command.startswith("/sbin/netifd") for r in rows)
    assert all(r.mem_kib >= 0 for r in rows)


def test_rc_list_parses() -> None:
    services = {r.name: r for r in parse_rc_list(_out(s.RC_LIST))}
    assert len(services) >= 25
    assert (services["dropbear"].enabled, services["dropbear"].running) == (True, True)
    assert (services["cron"].enabled, services["cron"].running) == (True, False)  # no crontab on AP2
    assert services["odhcpd"].enabled is False
    assert services["boot"].running is False  # no "running" key: a one-shot script


def test_timezones_parse() -> None:
    zones = parse_timezones(_out(s.TIMEZONES))
    assert len(zones) > 400
    assert zones["Asia/Jerusalem"] == "IST-2IDT,M3.4.4/26,M10.5.0" and zones["Etc/GMT"] == "GMT0"
    assert "UTC" not in zones  # AP2 is set to UTC: the app offers it itself, as LuCI does


def test_live_parses() -> None:
    sample = parse_live(_out(s.LIVE), 0.0)
    assert sample.load1 is not None and sample.connections is not None
    assert "eth0" in sample.interfaces and "wwan0" in sample.interfaces and "lo" not in sample.interfaces
    conns = parse_conntrack(_out(s.CONNTRACK))
    assert conns and all(c.proto in ("tcp", "udp", "icmp", "icmpv6") for c in conns)


def test_crontab_state() -> None:
    absent = RECORDING[s.CRONTAB]
    assert absent["exit"] == 1 and "No such file" in str(absent.get("stderr"))
    assert _out(s.RC_LOCAL).rstrip().endswith("exit 0")


def test_backup_size_only() -> None:
    assert int(_out(s.BACKUP_SIZE).strip()) > 1000
    assert s.BACKUP not in RECORDING  # the archive holds secrets: never recorded
