"""The reads Discovery, the /rom profile and the flash checks send; each runs as its own exec.

Every text here is read-only (`guard/readonly.py` accepts exactly these); a name or path put into one is
checked with `re.fullmatch` first.
"""

from __future__ import annotations

import re

from openwrtgui.uci import shell_quote

OVERLAY_LS = "find /overlay/upper -xdev ! -type d -exec ls -ldn {} +"
ROM_LS = "find /rom -xdev ! -type d -exec ls -ldn {} +"
APK_DB = "cat /lib/apk/db/installed"
OPKG_STATUS = "cat /usr/lib/opkg/status"
CONFIG_LIST = "ls /etc/config"
SYSUPGRADE_LIST = "sysupgrade -l"
PROC_MTD = "cat /proc/mtd"
MEMINFO = "cat /proc/meminfo"
DF_TMP = "df -k /tmp"
ROM_RELEASE = "cat /rom/etc/openwrt_release"
ROM_APK_DB = "cat /rom/lib/apk/db/installed"
ROM_OPKG_STATUS = "cat /rom/usr/lib/opkg/status"
ROM_CONFIG_LIST = "ls /rom/etc/config"
ROM_SERVICES = "ls /rom/etc/init.d"
ROM_UCI_DEFAULTS = "ls /rom/etc/uci-defaults"

CONFIG_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/+@:=,-]{1,255}")


def _name(name: str) -> str:
    if not CONFIG_NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a config name")
    return name


def _path(path: str) -> str:
    if not SAFE_PATH.fullmatch(path) or "/../" in f"{path}/":
        raise ValueError(f"{path!r} has characters a read does not take")
    return path


def uci_show(config: str) -> str:
    return f"uci show {_name(config)}"


def rom_config(config: str) -> str:
    return f"cat /rom/etc/config/{_name(config)}"


def rom_head(path: str) -> str:
    return f"head -c 6000 {shell_quote('/rom' + _path(path))}"


def head(path: str) -> str:
    return f"head -c 6000 {shell_quote(_path(path))}"


def firmware_hash(index: int, length: int) -> str:
    count = -(-length // 65536)
    return f"dd if=/dev/mtdblock{index} bs=65536 count={count} 2>/dev/null | head -c {length} | sha256sum"
