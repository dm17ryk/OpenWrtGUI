"""simsystem.py through the whole simulator: system config, services, files, diagnostics, backup, reboot."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from openwrtgui.simulator import SimConnector, sim_commands
from openwrtgui.system import commands as s
from openwrtgui.system.parse import (
    parse_board,
    parse_dmesg,
    parse_live,
    parse_logread,
    parse_rc_list,
    parse_top,
)
from openwrtgui.transport.base import Unreachable
from openwrtgui.transport.fake import ReplayTransport

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _ap2(clock: Clock) -> ReplayTransport:
    state = SimConnector(SIM_DIR, clock).state("192.168.1.2")
    return ReplayTransport(sim_commands(SIM_DIR, "ap2"), state=state)


async def _out(t: ReplayTransport, command: str) -> str:
    result = await t.run(command)
    assert result.exit_status == 0, (command, result.stderr)
    return result.stdout


def _services(text: str) -> dict[str, tuple[bool, bool]]:
    return {r.name: (r.enabled, r.running) for r in parse_rc_list(text)}


async def test_sim_uci_system_round_trip() -> None:
    t = _ap2(Clock())
    shown = await _out(t, s.UCI_SYSTEM)
    assert "system.cfg01e48a.hostname='OpenWrt'" in shown and "system.ntp.enable_server='0'" in shown
    script = "set -e\nuci set system.cfg01e48a.hostname='bench-ap2'\n"
    script += "uci set system.cfg01e48a.zonename='Asia/Jerusalem'\n"
    script += "uci set system.cfg01e48a.timezone='IST-2IDT,M3.4.4/26,M10.5.0'\nuci commit system"
    assert (await t.run(script)).exit_status == 0
    assert "hostname='bench-ap2'" in await _out(t, s.UCI_SYSTEM)
    board = parse_board(await _out(t, s.BOARD))
    assert board is not None and board.hostname == "OpenWrt"  # applied only by the reload
    assert await _out(t, s.TZ_FILE) == "GMT0\n"
    assert (await t.run(s.init("system", "reload"))).exit_status == 0  # type: ignore[arg-type]
    board = parse_board(await _out(t, s.BOARD))
    assert board is not None and board.hostname == "bench-ap2"
    assert await _out(t, s.TZ_FILE) == "IST-2IDT,M3.4.4/26,M10.5.0\n"
    zones = json.loads(await _out(t, s.TIMEZONES))
    assert zones["Asia/Jerusalem"] == {"tzstring": "IST-2IDT,M3.4.4/26,M10.5.0", "active": True}


async def test_sim_services_follow_actions() -> None:
    t = _ap2(Clock())
    services = _services(await _out(t, s.RC_LIST))
    assert services["sysntpd"] == (True, True) and services["odhcpd"] == (False, False)
    assert (
        services["dropbear"] == (True, True) and "dwr921-internet-led" in services
    )  # the image's custom one
    assert (await t.run(s.init("sysntpd", "stop"))).exit_status == 0
    assert _services(await _out(t, s.RC_LIST))["sysntpd"] == (True, False)
    assert (await t.run(s.init("sysntpd", "start"))).exit_status == 0
    assert (await t.run(s.init("urandom_seed", "disable"))).exit_status == 0
    after = _services(await _out(t, s.RC_LIST))
    assert after["sysntpd"] == (True, True) and after["urandom_seed"][0] is False
    assert (await t.run(s.init("dwr921-internet-led", "disable"))).exit_status == 0
    assert _services(await _out(t, s.RC_LIST))["dwr921-internet-led"][0] is False
    missing = await t.run(s.init("nosuch", "start"))
    assert missing.exit_status == 127 and "not found" in missing.stderr


async def test_sim_crontab_write_and_cron_restart() -> None:
    t = _ap2(Clock())
    absent = await t.run(s.CRONTAB)
    assert absent.exit_status == 1 and "No such file" in absent.stderr
    assert (await _out(t, s.RC_LOCAL)).rstrip().endswith("exit 0")
    assert (await t.run(s.write_file("/etc/crontabs/root", "*/5 * * * * logger owg-test\n"))).exit_status == 0
    assert await _out(t, s.CRONTAB) == "*/5 * * * * logger owg-test\n"
    assert (await t.run(s.init("cron", "restart"))).exit_status == 0
    assert _services(await _out(t, s.RC_LIST))["cron"] == (True, True)
    assert (await t.run(s.write_file("/etc/rc.local", "echo hi\nexit 0"))).exit_status == 0
    assert await _out(t, s.RC_LOCAL) == "echo hi\nexit 0\n"


async def test_sim_reboot_comes_back_with_a_fresh_uptime() -> None:
    clock = Clock()
    t = _ap2(clock)
    assert float((await _out(t, "cat /proc/uptime")).split()[0]) >= 86400
    assert (await t.run(s.init("sysntpd", "stop"))).exit_status == 0
    assert (await t.run("reboot")).exit_status == 0
    with pytest.raises(Unreachable):
        await t.run("cat /proc/uptime")
    clock.now += 30
    assert float((await _out(t, "cat /proc/uptime")).split()[0]) < 30
    assert _services(await _out(t, s.RC_LIST))["sysntpd"] == (True, True)  # enabled, so started at boot


async def test_sim_backup_stream() -> None:
    t = _ap2(Clock())
    stream = await t.stream(s.BACKUP)
    data = b""
    while chunk := await stream.read():
        data += chunk
    await stream.close()
    assert stream.exit_status == 0
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        names = tar.getnames()
    assert "etc/config/system" in names and "etc/rc.local" in names
    assert int((await _out(t, s.BACKUP_SIZE)).strip()) == len(data)


async def test_sim_reads_and_diagnostics() -> None:
    clock = Clock()
    t = _ap2(clock)
    assert parse_logread(await _out(t, s.logread(100)))
    assert parse_dmesg(await _out(t, s.DMESG))
    rows, cpu = parse_top(await _out(t, s.TOP))
    assert rows and cpu
    first = parse_live(await _out(t, s.LIVE), clock.now)
    clock.now += 3
    second = parse_live(await _out(t, s.LIVE), clock.now)
    assert second.interfaces["br-lan"][0] > first.interfaces["br-lan"][0] and first.connections
    assert "ESTABLISHED" in await _out(t, s.CONNTRACK)
    ping = await _out(t, s.ping("192.168.1.10"))
    assert ping.count("bytes from 192.168.1.10") == 4
    bad = await t.run(s.ping("nohost.invalid"))
    assert bad.exit_status == 1 and "bad address" in bad.stderr
    assert "Name:" in await _out(t, s.nslookup("openwrt.org"))
    assert (await _out(t, s.traceroute("8.8.8.8"))).startswith("traceroute to 8.8.8.8")
