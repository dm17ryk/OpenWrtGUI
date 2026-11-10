"""system/commands.py: the write builders and the rules every value matches first."""

from __future__ import annotations

import pytest

from openwrtgui.system import commands as s


def test_init_scripts() -> None:
    assert s.init("sysntpd", "restart") == "/etc/init.d/sysntpd restart"
    assert s.init("urandom_seed", "disable") == "/etc/init.d/urandom_seed disable"


def test_diagnostics_are_bounded() -> None:
    assert s.ping("192.168.1.10") == "timeout -s KILL 25 ping -c 4 -W 2 '192.168.1.10'"
    assert s.traceroute("openwrt.org") == "timeout -s KILL 25 traceroute -m 15 -w 2 -q 1 -n 'openwrt.org'"
    assert s.nslookup("fe80::1") == "timeout -s KILL 25 nslookup 'fe80::1'"


@pytest.mark.parametrize(
    ("build", "value"),
    [
        (lambda v: s.init(v, "start"), "x y"),
        (lambda v: s.init(v, "start"), "../x"),
        (s.ping, "-c 100 x"),
        (s.ping, "a;b"),
        (s.ping, ""),
        (s.traceroute, "x" * 254),
        (s.nslookup, "$(id)"),
    ],
)
def test_commands_refuse_unsafe_values(build, value: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        build(value)


def test_init_refuses_other_actions() -> None:
    with pytest.raises(ValueError):
        s.init("cron", "reload; reboot")  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["OpenWrt", "bench-ap2", "a", "a" * 63, "ap2x9"])
def test_hostname_rule_accepts(name: str) -> None:
    assert s.HOSTNAME.fullmatch(name)


@pytest.mark.parametrize("name", ["-x", "x-", "a_b", "a" * 64, "", "a.b"])
def test_hostname_rule_refuses(name: str) -> None:
    assert not s.HOSTNAME.fullmatch(name)


def test_write_file() -> None:
    assert (
        s.write_file("/etc/rc.local", "# local\nexit 0\n")
        == "cat > /etc/rc.local <<'OWG'\n# local\nexit 0\nOWG"
    )
    assert s.write_file("/etc/crontabs/root", "*/5 * * * * logger x") == (
        "mkdir -p /etc/crontabs && cat > /etc/crontabs/root <<'OWG'\n*/5 * * * * logger x\nOWG"
    )


def test_write_file_refuses_owg_and_9_kib() -> None:
    with pytest.raises(ValueError, match="OWG"):
        s.write_file("/etc/rc.local", "echo\nOWG\nexit 0")
    with pytest.raises(ValueError, match="^The file is at most 8 KiB$"):
        s.write_file("/etc/rc.local", "x" * 9 * 1024)
    with pytest.raises(ValueError):
        s.write_file("/etc/passwd", "x")  # type: ignore[arg-type]
