"""A simulated router with a later image (v1.0a2 D7): what the bench image lacks, from
tests/fixtures/sim/later/. The menu and ACL reads get the image's extra files; block-mount, iptables and a
LuCI plugin answer as on a router that has them."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from typing import Any

from openwrtgui.transport.base import CommandResult

_MENU = "for f in /usr/share/luci/menu.d/"
_ACL = "for f in /usr/share/rpcd/acl.d/"
_LISTING = re.compile(r"(ip6?tables) --line-numbers -w -nvxL -t (filter|nat|mangle|raw)")
_RULE_COUNTERS = re.compile(r"^(\d+\s+)\d+(\s+)\d+", re.MULTILINE)
_POLICY_COUNTERS = re.compile(r"\d+ packets, \d+ bytes")
PLUGIN_DIR = "/www/luci-static/resources/view/plugins"
TAB = "\t"


def _ok(command: str, stdout: str = "") -> CommandResult:
    return CommandResult(command, stdout, "", 0)


def _fail(command: str, stderr: str, status: int = 1) -> CommandResult:
    return CommandResult(command, "", stderr, status)


def _files(spec: Mapping[str, Any]) -> str:
    return "".join(f"=== {path}\n{json.dumps(body, indent=TAB)}\n" for path, body in spec.items())


class SimLater:
    def __init__(self, spec: Mapping[str, Any], base: Mapping[str, CommandResult]) -> None:
        self._spec = spec
        self._base = base
        self._mounts = str(spec["mounts"])
        self._zeroed: set[str] = set()

    def _extended(self, command: str, extra: Mapping[str, Any]) -> CommandResult:
        recorded = self._base[command]
        return CommandResult(command, recorded.stdout + _files(extra), recorded.stderr, recorded.exit_status)

    def _listing(self, command: str, program: str, table: str) -> CommandResult:
        text = str(self._spec[program][table])
        if program in self._zeroed and table == "filter":  # -Z without -t: the filter table only
            text = _POLICY_COUNTERS.sub("0 packets, 0 bytes", _RULE_COUNTERS.sub(r"\g<1>0\g<2>0", text))
        return _ok(command, text)

    def _unmount(self, command: str) -> CommandResult:
        target = shlex.split(command)[1]
        lines = self._mounts.splitlines(keepends=True)
        kept = [line for line in lines if line.split()[1:2] != [target]]
        if len(kept) == len(lines):
            return _fail(command, f"umount: can't unmount {target}: Invalid argument\n")
        self._mounts = "".join(kept)
        return _ok(command)

    def _plugin(self, command: str) -> CommandResult:
        name = command.removeprefix(f"cat {PLUGIN_DIR}/")
        text = self._spec["plugins"].get(name)
        if text is None:
            return _fail(command, f"cat: can't open '{PLUGIN_DIR}/{name}': No such file or directory\n")
        return _ok(command, str(text))

    def answer(self, command: str) -> CommandResult | None:
        c = command.strip()
        if c.startswith(_MENU) and c in self._base:
            return self._extended(c, self._spec["menu"])
        if c.startswith(_ACL) and c in self._base:
            return self._extended(c, self._spec["acl"])
        exact = {
            "ubus call luci getBlockDevices": json.dumps(self._spec["block_devices"], indent=TAB) + "\n",
            "cat /proc/mounts": self._mounts,
            "df -k": str(self._spec["df"]),
            "block detect": str(self._spec["detect"]),
            "/sbin/block mount": "",
            "/etc/init.d/firewall restart": "",
            f"ls -1 {PLUGIN_DIR}": "".join(f"{name}\n" for name in sorted(self._spec["plugins"])),
        }
        if c in exact:
            return _ok(c, exact[c])
        if c.startswith("umount "):
            return self._unmount(c)
        if m := _LISTING.fullmatch(c):
            return self._listing(c, m.group(1), m.group(2))
        if c in ("iptables -Z", "ip6tables -Z"):
            self._zeroed.add(c.split()[0])
            return _ok(c)
        if c.startswith(f"cat {PLUGIN_DIR}/"):
            return self._plugin(c)
        return None
