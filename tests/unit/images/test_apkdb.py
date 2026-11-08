"""images/apkdb.py: apk and opkg package databases, and which packages are the bench's own (custom)."""

from __future__ import annotations

from openwrtgui.images.apkdb import Package, is_custom, parse_apk_installed, parse_opkg_status

PORTCTL = (
    "C:Q1veLx0mrYTaXYAC2YE2pcHi6Mwz0=\nP:dwr921-portctl\nV:2\nA:mipsel_24kc\n"
    "T:Safe label-based enable/disable/status operations\nU:\nL:\n"
    "o:feeds/base/network/utils/dwr921-portctl\nD:libc swconfig\n"
    "F:usr/sbin\nR:dwr921-portctl\na:0:0:755\nZ:Q1abc=\nF:usr/share/dwr921-portctl\nR:ports\n"
)
BUSYBOX = "P:busybox\nV:1.37.0-r6\nT:The Swiss Army Knife\nU:https://busybox.net/\nL:GPL-2.0\nF:bin\nR:busybox\nR:sh\n"


def test_apk_block_with_files() -> None:
    (p,) = parse_apk_installed(PORTCTL)
    assert (p.name, p.version, p.origin) == ("dwr921-portctl", "2", "feeds/base/network/utils/dwr921-portctl")
    assert p.description == "Safe label-based enable/disable/status operations"
    assert p.files == ("/usr/sbin/dwr921-portctl", "/usr/share/dwr921-portctl/ports")
    assert p.depends == ("libc", "swconfig")
    assert is_custom(p)


def test_several_blocks_and_blank_lines() -> None:
    packages = parse_apk_installed("\n" + PORTCTL + "\n\n" + BUSYBOX + "\n\n")
    assert [p.name for p in packages] == ["dwr921-portctl", "busybox"]
    assert packages[1].files == ("/bin/busybox", "/bin/sh")


def test_upstream_package_is_not_custom() -> None:
    assert not is_custom(Package(name="a", version="1", license="GPL-2.0"))
    assert not is_custom(Package(name="b", version="1", url="https://example.org/"))
    assert is_custom(Package(name="c", version="1", license=" ", url=""))


def test_block_without_a_name_is_skipped() -> None:
    assert parse_apk_installed("V:1\nT:orphan\n\n" + BUSYBOX) == (parse_apk_installed(BUSYBOX)[0],)


def test_opkg_status_with_lists() -> None:
    status = (
        "Package: foo\nVersion: 1.2-r1\nDepends: libc, libubox20240329 (>= 2024)\nLicense: MIT\n"
        "Description: First line\n continued here\nStatus: install user installed\n\n"
        "Package: bar\nVersion: 3\nStatus: install user installed\n"
    )
    foo, bar = parse_opkg_status(status, {"foo": "/usr/bin/foo\n/etc/config/foo\n"})
    assert (foo.name, foo.version, foo.license) == ("foo", "1.2-r1", "MIT")
    assert foo.description == "First line continued here"
    assert foo.depends == ("libc", "libubox20240329")
    assert foo.files == ("/usr/bin/foo", "/etc/config/foo")
    assert (bar.name, bar.files) == ("bar", ())
    assert is_custom(bar)
