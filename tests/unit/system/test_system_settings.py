"""system/settings.py: the System and time form as uci ops on AP2's `system` sections, plus what to reload."""

from __future__ import annotations

import pytest

from openwrtgui.system.settings import SystemSettings, current_settings, settings_ops
from openwrtgui.uci import UciOp

SEC = "system.cfg01e48a"
CURRENT = {
    SEC: "system",
    f"{SEC}.hostname": "OpenWrt",
    f"{SEC}.timezone": "GMT0",
    f"{SEC}.zonename": "UTC",
    f"{SEC}.log_size": "128",
    "system.ntp": "timeserver",
    "system.ntp.enabled": "1",
    "system.ntp.enable_server": "0",
    "system.ntp.server": "0.openwrt.pool.ntp.org 1.openwrt.pool.ntp.org",
}
ZONES = {"UTC": "GMT0", "Asia/Jerusalem": "IST-2IDT,M3.4.4/26,M10.5.0"}


def test_current_settings() -> None:
    s = current_settings(CURRENT)
    assert (s.hostname, s.zonename, s.ntp_client, s.ntp_server, s.log_size, s.log_ip) == (
        "OpenWrt",
        "UTC",
        True,
        False,
        128,
        "",
    )
    assert s.ntp_servers == ("0.openwrt.pool.ntp.org", "1.openwrt.pool.ntp.org")


def test_hostname() -> None:
    ops, reloads = settings_ops(CURRENT, SystemSettings(hostname="bench-ap2"), ZONES)
    assert ops == [UciOp("set", f"{SEC}.hostname", "bench-ap2")]
    assert reloads == ["/etc/init.d/system reload"]


def test_zone_sets_both_names() -> None:
    ops, reloads = settings_ops(CURRENT, SystemSettings(zonename="Asia/Jerusalem"), ZONES)
    assert ops == [
        UciOp("set", f"{SEC}.zonename", "Asia/Jerusalem"),
        UciOp("set", f"{SEC}.timezone", "IST-2IDT,M3.4.4/26,M10.5.0"),
    ]
    assert reloads == ["/etc/init.d/system reload"]


def test_ntp_servers_and_switches() -> None:
    servers = ("pool.ntp.org", "192.168.1.10")
    ops, reloads = settings_ops(CURRENT, SystemSettings(ntp_servers=servers, ntp_server=True), ZONES)
    assert ops == [
        UciOp("set", "system.ntp.enable_server", "1"),
        UciOp("delete", "system.ntp.server"),
        UciOp("add_list", "system.ntp.server", "pool.ntp.org"),
        UciOp("add_list", "system.ntp.server", "192.168.1.10"),
    ]
    assert reloads == ["/etc/init.d/sysntpd restart"]
    same = ("0.openwrt.pool.ntp.org", "1.openwrt.pool.ntp.org")
    assert settings_ops(CURRENT, SystemSettings(ntp_servers=same), ZONES) == ([], [])


def test_remote_syslog_set_and_removed() -> None:
    ops, reloads = settings_ops(
        CURRENT, SystemSettings(log_ip="192.168.1.10", log_port=514, log_proto="udp", log_size=256), ZONES
    )
    assert ops == [
        UciOp("set", f"{SEC}.log_size", "256"),
        UciOp("set", f"{SEC}.log_ip", "192.168.1.10"),
        UciOp("set", f"{SEC}.log_port", "514"),
        UciOp("set", f"{SEC}.log_proto", "udp"),
    ]
    assert reloads == ["/etc/init.d/system reload", "/etc/init.d/log restart"]
    remote = CURRENT | {f"{SEC}.log_ip": "192.168.1.10", f"{SEC}.log_port": "514"}
    ops, reloads = settings_ops(remote, SystemSettings(log_ip=""), ZONES)
    assert ops == [UciOp("delete", f"{SEC}.log_ip"), UciOp("delete", f"{SEC}.log_port")]
    assert reloads == ["/etc/init.d/log restart"]
    assert settings_ops(CURRENT, SystemSettings(log_ip=""), ZONES) == ([], [])  # none to remove


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (
            SystemSettings(hostname="-x"),
            "A hostname is 1 to 63 letters, digits or -, not starting or ending with -",
        ),
        (
            SystemSettings(hostname="a_b"),
            "A hostname is 1 to 63 letters, digits or -, not starting or ending with -",
        ),
        (
            SystemSettings(hostname="a" * 64),
            "A hostname is 1 to 63 letters, digits or -, not starting or ending with -",
        ),
        (SystemSettings(zonename="Mars/Base"), "Mars/Base is not a time zone this router knows"),
        (SystemSettings(log_size=8), "The log buffer is 16 to 1024 KiB"),
        (SystemSettings(log_size=2048), "The log buffer is 16 to 1024 KiB"),
        (SystemSettings(log_ip="10.0.0.1", log_port=70000), "The remote syslog port is 1 to 65535"),
        (SystemSettings(log_ip="x"), "x is not an IPv4 address"),
        (SystemSettings(ntp_servers=("-x",)), "'-x' is not an NTP server name or address"),
    ],
)
def test_system_settings_refusals(settings: SystemSettings, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        settings_ops(CURRENT, settings, ZONES)
