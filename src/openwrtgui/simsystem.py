"""The simulated System side of a router (v0.6b plan Task 3): board and info with the applied hostname, time
zones, logs, processes, init scripts (`rc list`, start/stop/restart/enable/disable/reload), /etc/rc.local and
the crontab, live counters, the connection table, diagnostics, the backup archive and a plain reboot.

The `system` uci config itself lives in the network simulator (it already stages and commits uci scripts);
this reads the committed values from there. Hostname and time zone take effect on `/etc/init.d/system reload`
or a reboot, as on the router."""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from openwrtgui.system import commands as s
from openwrtgui.transport.base import CommandResult

if TYPE_CHECKING:
    from openwrtgui.simimage import SimImage
    from openwrtgui.simnet import SimNetwork

# AP2's init scripts as `rc list` showed them (2026-11-09): name -> (start, enabled). Daemons run while
# enabled; cron only while a crontab exists; the rest run once at boot (procd keeps no instance of them).
_DAEMONS = frozenset(
    {"cron", "dnsmasq", "dropbear", "log", "network", "rpcd", "sysntpd", "uhttpd", "urngd", "wpad"}
)
_NO_INSTANCE = frozenset({"boot", "bootcount", "done", "led", "openssl", "sysctl", "sysfixtime", "umount"})
_AP2: dict[str, tuple[int | None, bool]] = {
    "boot": (10, True),
    "bootcount": (99, True),
    "cron": (50, True),
    "dnsmasq": (19, True),
    "done": (95, True),
    "dropbear": (19, True),
    "firewall": (19, True),
    "gpio_switch": (94, True),
    "led": (96, True),
    "log": (12, True),
    "network": (20, True),
    "odhcpd": (35, False),
    "openssl": (13, True),
    "packet_steering": (25, True),
    "radius": (30, True),
    "rpcd": (12, True),
    "socat": (99, True),
    "sysctl": (11, True),
    "sysfixtime": (0, True),
    "sysntpd": (98, True),
    "system": (10, True),
    "ucitrack": (80, True),
    "uhttpd": (50, True),
    "umount": (None, False),
    "urandom_seed": (99, True),
    "urngd": (0, True),
    "wpad": (19, True),
}
# a few of the router's 445 zones (AP2's list has no "UTC": LuCI adds that one itself)
TIMEZONES = {
    "Etc/GMT": "GMT0",
    "Asia/Jerusalem": "IST-2IDT,M3.4.4/26,M10.5.0",
    "Europe/London": "GMT0BST,M3.5.0/1,M10.5.0",
    "Europe/Berlin": "CET-1CEST,M3.5.0,M10.5.0/3",
    "America/New_York": "EST5EDT,M3.2.0,M11.1.0",
}
RC_LOCAL = (
    "# Put your custom commands here that should be executed once\n"
    "# the system init finished. By default this file does nothing.\n\nexit 0\n"
)
REBOOT_S = 20.0
_INIT = re.compile(r"/etc/init\.d/([A-Za-z0-9._-]+) (start|stop|restart|enable|disable|reload)")
_WRITE = re.compile(
    r"(?:mkdir -p /etc/crontabs && )?cat > (/etc/rc\.local|/etc/crontabs/root) <<'OWG'\n(.*)\nOWG", re.DOTALL
)
_DIAG = re.compile(
    r"timeout -s KILL 25 (ping -c 4 -W 2|traceroute -m 15 -w 2 -q 1 -n|nslookup) '([A-Za-z0-9.:-]+)'"
)
_LOGREAD = re.compile(r"logread -l (\d+)")
# per-interface byte rates the live counters grow by (rx, tx per second)
_RATES = {"br-lan": (12000, 30000), "eth0": (14000, 33000), "eth0.2": (0, 0), "wwan0": (2000, 4000)}
_CONNTRACK = (
    "ipv4     2 tcp      6 7440 ESTABLISHED src=192.168.1.10 dst=192.168.1.2 sport=53498 dport=22 packets=40 "
    "bytes=4000 src=192.168.1.2 dst=192.168.1.10 sport=22 dport=53498 packets=30 bytes=6000 [ASSURED] use=2\n"
    "ipv4     2 udp      17 29 src=192.168.1.2 dst=10.64.12.1 sport=5353 dport=53 packets=1 bytes=60 "
    "[UNREPLIED] src=10.64.12.1 dst=192.168.1.2 sport=53 dport=5353 packets=0 bytes=0 use=2\n"
    "ipv4     2 tcp      6 98 TIME_WAIT src=192.168.1.10 dst=192.168.1.2 sport=53510 dport=80 packets=6 "
    "bytes=900 src=192.168.1.2 dst=192.168.1.10 sport=80 dport=53510 packets=5 bytes=2400 [ASSURED] use=2\n"
)


def _ok(command: str, out: str = "") -> CommandResult:
    return CommandResult(command, out, "", 0)


def _fail(command: str, err: str, status: int = 1) -> CommandResult:
    return CommandResult(command, "", err, status)


class SimSystem:
    def __init__(
        self,
        *,
        clock: Callable[[], float],
        net: SimNetwork | None,
        image: SimImage | None,
        board_json: str | None = None,
        info_json: str | None = None,
        texts: Mapping[str, str] | None = None,
    ) -> None:
        self._clock = clock
        self._net = net
        self._image = image
        self._board = json.loads(board_json) if board_json else {}
        self._info = json.loads(info_json) if info_json else {}
        self._texts = dict(texts or {})
        self._files: dict[str, str] = {"/etc/rc.local": RC_LOCAL}
        self._services: dict[str, list[bool]] = {
            name: [enabled, self._runs_at_boot(name, enabled)] for name, (_start, enabled) in _AP2.items()
        }
        self._start = clock()
        self._boot_at = clock() - 86400.0  # used only without an image (the image keeps the real one)
        self._boot_seen = self._booted()
        self._applied = self._committed()

    # ---------------------------------------------------------------- state
    def _runs_at_boot(self, name: str, enabled: bool) -> bool:
        return self._starts(name) and enabled

    def _starts(self, name: str) -> bool:
        """What `start` leaves running: a daemon, and cron only with a crontab (its init script checks)."""
        if name == "cron":
            return bool(self._files.get("/etc/crontabs/root", "").strip())
        return name in _DAEMONS

    def _booted(self) -> float:
        return self._image.boot_at if self._image is not None else self._boot_at

    def _uptime(self) -> float:
        return self._clock() - self._booted()

    def _committed(self) -> dict[str, str]:
        """hostname and timezone as the committed system config has them."""
        uci = self._net.uci() if self._net is not None else {}
        section = next(
            (k for k, v in uci.items() if k.count(".") == 1 and k.startswith("system.") and v == "system"),
            None,
        )
        return {
            "hostname": uci.get(f"{section}.hostname", "OpenWrt") if section else "OpenWrt",
            "timezone": uci.get(f"{section}.timezone", "UTC0") if section else "UTC0",
            "zonename": uci.get(f"{section}.zonename", "UTC") if section else "UTC",
        }

    def _check_boot(self) -> None:
        """After a reboot the router comes up with its committed config and its enabled services."""
        booted = self._booted()
        if booted != self._boot_seen:
            self._boot_seen = booted
            self._applied = self._committed()
            for name, state in self._services.items():
                state[1] = self._runs_at_boot(name, state[0])

    def _rc(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        custom = self._image.custom_services if self._image is not None else {}
        for name, (enabled, running) in sorted(self._services.items()):
            start = _AP2.get(name, (50, True))[0]
            row: dict[str, Any] = {} if start is None else {"start": start}
            row["enabled"] = enabled
            if name not in _NO_INSTANCE:
                row["running"] = running
            out[name] = row
        for name, (running, enabled) in custom.items():
            out[name] = {"start": 97, "enabled": enabled, "running": running}
        return dict(sorted(out.items()))

    # ---------------------------------------------------------------- the archive
    def backup(self) -> bytes:
        uci = self._net.uci() if self._net is not None else {}
        files = {
            "etc/config/system": "".join(f"{k}={v}\n" for k, v in uci.items() if k.startswith("system."))
        }
        files["etc/rc.local"] = self._files["/etc/rc.local"]
        if "/etc/crontabs/root" in self._files:
            files["etc/crontabs/root"] = self._files["/etc/crontabs/root"]
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            for name, text in files.items():
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size, info.mtime = len(data), 1793700000
                tar.addfile(info, io.BytesIO(data))
        return gzip.compress(raw.getvalue(), mtime=0)

    def stream(self, command: str) -> bytes | None:
        return self.backup() if command == s.BACKUP else None

    # ---------------------------------------------------------------- commands
    def answer(self, command: str) -> CommandResult | None:  # noqa: PLR0911 - one branch per command
        self._check_boot()
        c = command
        if c == s.BOARD and self._board:
            return _ok(
                c, json.dumps({**self._board, "hostname": self._applied["hostname"]}, indent="\t") + "\n"
            )
        if c == s.INFO and self._info:
            return _ok(c, json.dumps({**self._info, "uptime": int(self._uptime())}, indent="\t") + "\n")
        if c == s.TZ_FILE:
            return _ok(c, self._applied["timezone"] + "\n")
        if c == s.TIMEZONES:
            zones: dict[str, dict[str, Any]] = {name: {"tzstring": tz} for name, tz in TIMEZONES.items()}
            if self._applied["zonename"] in zones:
                zones[self._applied["zonename"]]["active"] = True
            return _ok(c, json.dumps(zones) + "\n")
        if c == s.RC_LIST:
            return _ok(c, json.dumps(self._rc(), indent="\t") + "\n")
        if c in (s.TOP, s.DMESG):
            return _ok(c, self._texts.get("top" if c == s.TOP else "dmesg", ""))
        if m := _LOGREAD.fullmatch(c):
            lines = self._texts.get("logread", "").splitlines(keepends=True)
            return _ok(c, "".join(lines[-int(m.group(1)) :]))
        if c in (s.RC_LOCAL, s.CRONTAB):
            path = c.split(" ", 1)[1]
            if path not in self._files:
                return _fail(c, f"cat: can't open '{path}': No such file or directory\n")
            return _ok(c, self._files[path])
        if m := _WRITE.fullmatch(c):
            self._files[m.group(1)] = m.group(2) + "\n"
            return _ok(c)
        if c == s.LIVE:
            return _ok(c, self._live())
        if c == s.CONNTRACK:
            return _ok(c, _CONNTRACK)
        if c == s.BACKUP_SIZE:
            return _ok(c, f"{len(self.backup())}\n")
        if m := _INIT.fullmatch(c):
            return self._init(c, m.group(1), m.group(2))
        if m := _DIAG.fullmatch(c):
            return self._diag(c, m.group(1).split()[0], m.group(2))
        if c == "reboot":
            if self._image is not None:
                self._image.reboot(REBOOT_S)
            else:
                self._boot_at = self._clock()
            return _ok(c)
        if c == "cat /proc/uptime" and self._image is None:
            up = self._uptime()
            return _ok(c, f"{up:.2f} {up * 0.9:.2f}\n")
        return None

    def _init(self, c: str, name: str, action: str) -> CommandResult:
        custom = self._image.custom_services if self._image is not None else {}
        if name in custom:  # start/stop/restart of these the image answers; enable/disable come here
            if action in ("enable", "disable"):
                custom[name][1] = action == "enable"
            return _ok(c)
        if name not in self._services:
            return _fail(c, f"/bin/ash: /etc/init.d/{name}: not found\n", 127)
        state = self._services[name]
        if action in ("enable", "disable"):
            state[0] = action == "enable"
        elif action in ("start", "restart"):
            state[1] = self._starts(name)
        elif action == "stop":
            state[1] = False
        if name == "system" and action in ("reload", "restart", "start"):
            self._applied = self._committed()
        return _ok(c)

    def _live(self) -> str:
        elapsed = self._clock() - self._start
        dev = (
            "Inter-|   Receive |  Transmit\n face |bytes packets errs drop fifo frame compr multicast|bytes\n"
        )
        dev += "    lo: 1000 10 0 0 0 0 0 0 1000 10 0 0 0 0 0 0\n"
        for name, (rx, tx) in _RATES.items():
            received, sent = 5_000_000 + int(rx * elapsed), 9_000_000 + int(tx * elapsed)
            dev += f" {name}: {received} 4000 0 0 0 0 0 0 {sent} 5000 0 0 0 0 0 0\n"
        return f"0.16 0.03 0.01 2/52 25700\n{dev}42\n"

    def _diag(self, c: str, tool: str, target: str) -> CommandResult:
        if target.endswith(".invalid") or target.startswith("nohost"):
            return _fail(c, f"{tool}: bad address '{target}'\n")
        address = target if re.fullmatch(r"[\d.]+|[0-9a-fA-F:]+", target) else "93.184.216.34"
        if tool == "ping":
            replies = "".join(
                f"64 bytes from {address}: seq={i} ttl=64 time=0.{512 + i} ms\n" for i in range(4)
            )
            tail = f"\n--- {target} ping statistics ---\n4 packets transmitted, 4 packets received, 0% loss\n"
            return _ok(c, f"PING {target} ({address}): 56 data bytes\n{replies}{tail}")
        if tool == "traceroute":
            hops = f" 1  192.168.1.1  0.512 ms\n 2  10.64.12.1  20.104 ms\n 3  {address}  31.276 ms\n"
            return _ok(c, f"traceroute to {target} ({address}), 15 hops max, 46 byte packets\n{hops}")
        server = "Server:\t\t127.0.0.1\nAddress:\t127.0.0.1:53\n\n"
        return _ok(c, f"{server}Non-authoritative answer:\nName:\t{target}\nAddress: {address}\n")
