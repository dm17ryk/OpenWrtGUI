"""The simulated router's image side (v0.5): /rom, /overlay/upper, the package database, the configs, the
firmware partition, uploads, custom services and a reflash.

It answers only the exact commands it owns and is asked first, so it sees an upload, the sysupgrade.conf line
and the custom services before the Wi-Fi simulator's catch-all `echo` and the firewall's /tmp files do.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from openwrtgui.discovery import commands as cmd
from openwrtgui.flash.plan import KEEP_LINE
from openwrtgui.images.apkdb import is_custom, parse_apk_installed
from openwrtgui.images.sysupgrade import ImageError, open_root, parse_layout
from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.images.usage import usage_text
from openwrtgui.probe.identity import parse_release
from openwrtgui.transport.base import CommandResult
from openwrtgui.uci import shell_quote

# the network and Wi-Fi simulators' configs (system: the network simulator holds it for the System screen)
NOT_MINE = frozenset({"network", "dhcp", "firewall", "wireless", "system"})
REBOOT_S = 20.0  # how long a simulated flash keeps the router away (tests shorten it)
SYSUPGRADE_CONF = (
    "## This file contains files and directories that should\n## be preserved during an upgrade.\n"
)
PROC_MTD = (
    'dev:    size   erasesize  name\nmtd0: 00030000 00010000 "u-boot"\nmtd1: 00010000 00010000 "u-boot-env"\n'
    'mtd2: 00010000 00010000 "factory"\nmtd3: 00fb0000 00010000 "firmware"\n'
    'mtd4: 002d8a69 00010000 "kernel"\nmtd5: 00cd7597 00010000 "rootfs"\n'
    'mtd6: 00670000 00010000 "rootfs_data"\n'
)
_HELP = re.compile(r"timeout 5 (/\S+) --help 2>&1 \| head -c 8192")
_SERVICE_LIST = re.compile(r"ubus call service list '\{\"name\":\"([A-Za-z0-9._-]+)\"\}'")
_INIT = re.compile(r"/etc/init\.d/([A-Za-z0-9._-]+) (start|stop|restart)")
_ENABLED = re.compile(r"/etc/init\.d/([A-Za-z0-9._-]+) enabled; echo \$\?")
_VALIDATE = re.compile(r"ubus call system validate_firmware_image '\{\"path\":\"(/tmp/\S+)\"\}'")
_SYSUPGRADE = re.compile(r"sysupgrade (-T |-n )?(/tmp/\S+)")
_FIRMWARE = re.compile(r"dd if=/dev/mtdblock3 bs=65536 count=\d+ 2>/dev/null \| head -c (\d+) \| sha256sum")


@dataclass
class _Node:
    kind: str  # "file", "link" or "whiteout"
    mode: int
    data: bytes = b""
    target: str = ""


def _ok(command: str, out: str = "") -> CommandResult:
    return CommandResult(command, out, "", 0)


def _fail(command: str, err: str, status: int = 1) -> CommandResult:
    return CommandResult(command, "", err, status)


def _mode_string(node: _Node) -> str:
    bits = "".join(c if node.mode & (0o400 >> i) else "-" for i, c in enumerate("rwxrwxrwx"))
    return ("l" if node.kind == "link" else "-") + bits


def _ls(prefix: str, path: str, node: _Node) -> str:
    if node.kind == "whiteout":
        return f"c---------    1 0        0          0,   0 Nov  7 15:24 {prefix}{path}"
    size = len(node.target) if node.kind == "link" else len(node.data)
    line = f"{_mode_string(node)}    1 0        0        {size:>8} Nov  7 15:24 {prefix}{path}"
    return line + (f" -> {node.target}" if node.kind == "link" else "")


def _uci_show(config: str, text: str) -> str:
    lines = []
    for key, value in parse_uci_file(config, text).items():
        lines.append(f"{key}={value}" if key.count(".") == 1 else f"{key}={shell_quote(value)}")
    return "".join(f"{line}\n" for line in lines)


class SimImage:
    def __init__(
        self,
        image: bytes,
        upper: Mapping[str, Any],
        *,
        clock: Callable[[], float],
        board_json: str | None = None,
        reboot_s: float | None = None,
    ) -> None:
        self._clock = clock
        self._reboot_s = reboot_s
        self._board_json = board_json
        self._load(image)
        layout = parse_layout(image, "image")
        self._board = layout.metadata.supported_devices[0] if layout.metadata else ""
        self._firmware = image if upper.get("firmware_matches", True) else image[:100] + b"X" + image[101:]
        self._mem_kb = int(upper.get("mem_available_kb", 20480))
        self._tmp_kb = int(upper.get("tmp_free_kb", 24000))
        self._upper: dict[str, _Node] = {}
        for path, spec in upper.get("files", {}).items():
            self._upper[path] = _Node("file", int(spec.get("mode", "0644"), 8), spec["data"].encode())
        for path, target in upper.get("links", {}).items():
            self._upper[path] = _Node("link", 0o777, target=target)
        for path in upper.get("whiteouts", []):
            self._upper[path] = _Node("whiteout", 0)
        for name, text in upper.get("configs", {}).items():
            self._upper[f"/etc/config/{name}"] = _Node("file", 0o644, text.encode())
        self._extra_packages: list[str] = [block.strip("\n") for block in upper.get("packages", [])]
        self._tmp: dict[str, bytes] = {}
        self._conf = SYSUPGRADE_CONF
        self._services = {name: [True, True] for name in self._custom_services()}
        self._boot_at = clock() - 86400.0
        self._reboot_until: float | None = None
        self._pending: tuple[bytes, bool] | None = None
        self.flashed = False
        self.generation = 0
        self.address_reset = False

    # ---------------------------------------------------------------- state
    def _load(self, image: bytes) -> None:
        layout = parse_layout(image, "image")
        self._rom: dict[str, _Node] = {}
        for entry in open_root(image, layout).root.riter():
            if entry.path == "/" or entry.is_dir:
                continue
            if entry.is_symlink:
                self._rom[entry.path] = _Node("link", entry.mode & 0o7777, target=entry.readlink())
            else:
                self._rom[entry.path] = _Node("file", entry.mode & 0o7777, entry.read_bytes())

    @property
    def revision(self) -> str:
        return parse_release(self._rom["/etc/openwrt_release"].data.decode()).get("DISTRIB_REVISION", "")

    @property
    def rebooting(self) -> bool:
        if self._reboot_until is None:
            return False
        if self._clock() < self._reboot_until:
            return True
        if self._pending is None:
            self._finish_reboot()
        else:
            self._finish_flash()
        return False

    @property
    def boot_at(self) -> float:
        return self._boot_at

    @property
    def custom_services(self) -> dict[str, list[bool]]:
        """The bench's own services: name -> [running, enabled] (the System screen's rc list shows them)."""
        return self._services

    def reboot(self, seconds: float | None = None) -> None:
        """A plain reboot (the System screen's, v0.6b): away for `seconds`, then back with a fresh uptime."""
        away = seconds if seconds is not None else (REBOOT_S if self._reboot_s is None else self._reboot_s)
        self._reboot_until = self._clock() + away

    def _finish_reboot(self) -> None:
        assert self._reboot_until is not None
        self._boot_at = self._reboot_until
        self._reboot_until = None
        self._tmp = {}  # /tmp is RAM
        for state in self._services.values():
            state[0] = state[1]  # an enabled service starts at boot

    def _finish_flash(self) -> None:
        assert self._pending is not None and self._reboot_until is not None
        data, keep = self._pending
        kept = set(self._kept()) if keep else set()
        self._upper = {p: n for p, n in self._upper.items() if p in kept}
        self._load(data)
        self._firmware = data
        self._extra_packages = []
        self._tmp = {}
        if not keep:
            self._conf = SYSUPGRADE_CONF
            self.generation += 1
            self.address_reset = True
        self._services = {name: [True, True] for name in self._custom_services()}
        self._boot_at = self._reboot_until
        self._reboot_until = self._pending = None
        self.flashed = True

    def _live(self, path: str) -> _Node | None:
        node = self._upper.get(path, self._rom.get(path))
        return None if node is None or node.kind == "whiteout" else node

    def _db(self) -> str:
        rom = self._rom["/lib/apk/db/installed"].data.decode()
        return "\n\n".join([rom.strip("\n"), *self._extra_packages]) + "\n"

    def _listing(self) -> dict[str, _Node]:
        out = dict(self._upper)
        if self._extra_packages:
            out["/lib/apk/db/installed"] = _Node("file", 0o644, self._db().encode())
        return out

    def _configs(self) -> dict[str, str]:
        files = {**self._rom, **self._upper}
        return {
            p.rsplit("/", 1)[1]: n.data.decode()
            for p, n in files.items()
            if p.startswith("/etc/config/") and n.kind == "file"
        }

    def _custom_services(self) -> list[str]:
        owned = {f for p in parse_apk_installed(self._db()) for f in p.files}
        custom = {f for p in parse_apk_installed(self._db()) if is_custom(p) for f in p.files}
        names = [p for p in self._rom if p.startswith("/etc/init.d/") and p in custom]
        names += [
            p
            for p, n in self._upper.items()
            if p.startswith("/etc/init.d/") and n.kind == "file" and p not in owned
        ]
        return sorted({p.rsplit("/", 1)[1] for p in names})

    @property
    def sysupgrade_conf(self) -> str:
        """/etc/sysupgrade.conf (System edits it, v0.6c; a flash that keeps settings adds a line)."""
        return self._conf

    @sysupgrade_conf.setter
    def sysupgrade_conf(self, text: str) -> None:
        self._conf = text

    def _kept(self) -> list[str]:
        keep = ["/etc/sysupgrade.conf"]
        for path, node in self._rom.items():
            if path.startswith("/lib/upgrade/keep.d/"):
                keep += [w for w in node.data.decode().split() if not w.startswith("#")]
        keep += [
            line.strip() for line in self._conf.splitlines() if line.strip() and not line.startswith("#")
        ]
        return sorted(
            p
            for p, n in self._listing().items()
            if n.kind != "whiteout" and any(p == k or (k.endswith("/") and p.startswith(k)) for k in keep)
        )

    # ---------------------------------------------------------------- uploads and byte reads
    def upload(self, command: str, data: bytes) -> CommandResult | None:
        if m := re.fullmatch(r"cat > (/tmp/\S+)", command):
            self._tmp[m.group(1)] = data
            return _ok(command)
        if m := re.fullmatch(r"mkdir -p (\S+) && cat > (\S+)", command):
            path = m.group(2)
            if path.startswith("/tmp/"):
                self._tmp[path] = data
            else:
                self._upper[path] = _Node("file", 0o644, data)
            return _ok(command)
        return None

    def stream(self, command: str) -> bytes | None:
        if m := re.fullmatch(r"cat (/\S+)", command):
            node = self._live(m.group(1))
            if m.group(1) in self._tmp:
                return self._tmp[m.group(1)]
            return node.data if node is not None and node.kind == "file" else None
        return None

    # ---------------------------------------------------------------- commands
    def answer(self, command: str) -> CommandResult | None:  # noqa: PLR0911 - one branch per command shape
        c = command
        if c == cmd.OVERLAY_LS:
            return _ok(
                c, "".join(_ls("/overlay/upper", p, n) + "\n" for p, n in sorted(self._listing().items()))
            )
        if c == cmd.ROM_LS:
            return _ok(c, "".join(_ls("/rom", p, n) + "\n" for p, n in sorted(self._rom.items())))
        if c == cmd.APK_DB:
            return _ok(c, self._db())
        if c == cmd.ROM_APK_DB:
            return _ok(c, self._rom["/lib/apk/db/installed"].data.decode())
        if c == cmd.ROM_RELEASE or (c == "cat /etc/openwrt_release" and self.flashed):
            return _ok(c, self._rom["/etc/openwrt_release"].data.decode())
        if c == "ubus call system board" and self.flashed and self._board_json:
            return _ok(c, self._board_answer())
        if c == cmd.CONFIG_LIST:
            return _ok(c, "".join(f"{n}\n" for n in sorted(set(self._configs()) | NOT_MINE)))
        if c == cmd.ROM_CONFIG_LIST:
            names = sorted(p.rsplit("/", 1)[1] for p in self._rom if p.startswith("/etc/config/"))
            return _ok(c, "".join(f"{n}\n" for n in names))
        if m := re.fullmatch(r"cat /rom/etc/config/(\S+)", c):
            node = self._rom.get(f"/etc/config/{m.group(1)}")
            return (
                _ok(c, node.data.decode())
                if node
                else _fail(c, f"cat: can't open '/rom/etc/config/{m.group(1)}'\n")
            )
        if c in (cmd.ROM_SERVICES, cmd.ROM_UCI_DEFAULTS):
            folder = "/etc/init.d/" if c == cmd.ROM_SERVICES else "/etc/uci-defaults/"
            return _ok(c, "".join(p[len(folder) :] + "\n" for p in sorted(self._rom) if p.startswith(folder)))
        if (m := re.fullmatch(r"uci show ([A-Za-z0-9_.-]+)", c)) and m.group(1) not in NOT_MINE:
            text = self._configs().get(m.group(1))
            return (
                _ok(c, _uci_show(m.group(1), text))
                if text is not None
                else _fail(c, "uci: Entry not found\n")
            )
        if c == cmd.SYSUPGRADE_LIST:
            return _ok(c, "".join(f"{p}\n" for p in self._kept()))
        if c == cmd.PROC_MTD:
            return _ok(c, PROC_MTD)
        if c == cmd.MEMINFO:
            return _ok(
                c,
                f"MemTotal:          56208 kB\nMemFree:           12044 kB\n"
                f"MemAvailable:   {self._mem_kb:>8} kB\n",
            )
        if c == cmd.DF_TMP:
            return _ok(
                c,
                f"Filesystem           1K-blocks      Used Available Use% Mounted on\n"
                f"tmpfs                    28104       120 {self._tmp_kb:>9}   0% /tmp\n",
            )
        if c == "cat /proc/uptime":
            up = self._clock() - self._boot_at
            return _ok(c, f"{up:.2f} {up * 0.9:.2f}\n")
        if m := _FIRMWARE.fullmatch(c):
            return _ok(c, f"{hashlib.sha256(self._firmware[: int(m.group(1))]).hexdigest()}  -\n")
        return self._files(c) or self._services_answer(c) or self._flash(c)

    def _board_answer(self) -> str:
        board = json.loads(self._board_json or "{}")
        release = board.setdefault("release", {})
        release["revision"] = self.revision
        release["description"] = f"OpenWrt SNAPSHOT {self.revision}"
        return json.dumps(board, indent="\t") + "\n"

    def _files(self, c: str) -> CommandResult | None:
        if c.startswith("head -c 6000 "):
            path = shlex.split(c)[3]
            node = self._rom.get(path[4:]) if path.startswith("/rom/") else self._live(path)
            if node is None or node.kind != "file":
                return _fail(c, f"head: {path}: No such file or directory\n")
            return _ok(c, node.data[:6000].decode("utf-8", "replace"))
        if m := _HELP.fullmatch(c):
            node = self._live(m.group(1))
            if node is None:
                return _ok(c, f"sh: {m.group(1)}: not found\n")
            usage = usage_text(node.data)
            return _ok(c, f"{usage}\n" if usage else "")
        if c == KEEP_LINE:
            if "/etc/owg/" not in self._conf.split():
                self._conf += "/etc/owg/\n"
            return _ok(c)
        if c == "cat /etc/sysupgrade.conf":
            return _ok(c, self._conf)
        if m := re.fullmatch(r"sha256sum (/\S+)", c):
            data = self._tmp.get(m.group(1))
            node = self._live(m.group(1))
            if data is None and node is not None and node.kind == "file":
                data = node.data
            if data is None:
                return _fail(c, f"sha256sum: can't open '{m.group(1)}': No such file or directory\n")
            return _ok(c, f"{hashlib.sha256(data).hexdigest()}  {m.group(1)}\n")
        if m := re.fullmatch(r"readlink (/\S+)", c):
            node = self._live(m.group(1))
            return _ok(c, node.target + "\n") if node is not None and node.kind == "link" else _fail(c, "")
        if (m := re.fullmatch(r"chmod (0[0-7]{3}) (/\S+)", c)) and m.group(2) in self._upper:
            self._upper[m.group(2)].mode = int(m.group(1), 8)
            return _ok(c)
        if m := re.fullmatch(r"ln -sfn (\S+) (/\S+)", c):
            self._upper[m.group(2)] = _Node("link", 0o777, target=m.group(1))
            return _ok(c)
        if (m := re.fullmatch(r"rm -f (/tmp/owg/fw-\S+\.bin)", c)) and m.group(1) in self._tmp:
            del self._tmp[m.group(1)]
            return _ok(c)
        if (m := re.fullmatch(r"cat (/\S+)", c)) and m.group(1) in self._upper:
            node = self._upper[m.group(1)]
            return _ok(c, node.data.decode("utf-8", "replace")) if node.kind == "file" else None
        return None

    def _services_answer(self, c: str) -> CommandResult | None:
        if (m := _SERVICE_LIST.fullmatch(c)) and m.group(1) in self._services:
            name = m.group(1)
            if not self._services[name][0]:
                return _ok(c, "{\n}\n")
            body = {name: {"instances": {"instance1": {"running": True, "pid": 3101}}}}
            return _ok(c, json.dumps(body, indent="\t") + "\n")
        if (m := _INIT.fullmatch(c)) and m.group(1) in self._services:
            self._services[m.group(1)][0] = m.group(2) != "stop"
            return _ok(c)
        if (m := _ENABLED.fullmatch(c)) and m.group(1) in self._services:
            return _ok(c, "0\n" if self._services[m.group(1)][1] else "1\n")
        return None

    def _check(self, data: bytes | None) -> tuple[bool, bool]:
        """(valid, device matches) for an uploaded image, as validate_firmware_image tells it."""
        if data is None:
            return False, False
        try:
            layout = parse_layout(data, "image")
        except ImageError:
            return False, False
        device = layout.metadata is not None and self._board in layout.metadata.supported_devices
        return device, device

    def _flash(self, c: str) -> CommandResult | None:
        if m := _VALIDATE.fullmatch(c):
            valid, device = self._check(self._tmp.get(m.group(1)))
            tests = {"fwtool_signature": True, "fwtool_device_match": device}
            body = {"tests": tests, "valid": valid, "forceable": True, "allow_backup": True}
            return _ok(c, json.dumps(body, indent="\t") + "\n")
        if m := _SYSUPGRADE.fullmatch(c):
            flag, path = m.group(1), m.group(2)
            data = self._tmp.get(path)
            valid, _device = self._check(data)
            if data is None or not valid:
                return _fail(c, f"Device {self._board} not supported by this image\nImage check failed.\n")
            if flag == "-T ":
                return _ok(c)
            self._pending = (data, flag != "-n ")
            self._reboot_until = self._clock() + (REBOOT_S if self._reboot_s is None else self._reboot_s)
            return _ok(c, "Commencing upgrade. Closing all shell sessions.\n")
        return None
