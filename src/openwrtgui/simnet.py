"""A simulated router's network: uci (network, dhcp) with staging folders, rpcd apply/confirm/rollback,
`network.interface` state, routes, the swconfig switch, leases and the app's own path.

It answers the exact commands the app sends (plan v0.3, "Network rules"); anything else is not its
business and falls through to the other simulators and the recordings. A failed script leaves nothing
staged. The PC sits on switch port 3 at 192.168.1.10, so a change that moves lan out of its subnet, or
drops port 3 from lan's VLAN, or turns port 3 off, cuts the app off until the rollback restores it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shlex
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from openwrtgui.net.parse import devices, interfaces, routes, rules
from openwrtgui.ports.parse import render_members, switch_conf, switch_ports, switch_vlans
from openwrtgui.transport.base import CommandResult
from openwrtgui.uci import parse_uci_show, shell_quote

if TYPE_CHECKING:
    from openwrtgui.simmodem import SimModem

PC_MAC = "08:3a:88:5c:a8:39"
CONFIGS = ("network", "dhcp", "firewall", "system")  # system: the System screen's plain uci apply (v0.6b)
DEFAULT = ""  # the default staging folder (/tmp/.uci)
SWITCH = "switch0"
DEVICE_MACS = {"br-lan": "00:0c:43:76:20:17", "eth0.1": "00:0c:43:76:20:17", "eth0.2": "00:0c:43:76:20:16"}
EXTERNAL = (0, 1, 2, 3, 4)
CPU = 6
PORTS = 8
_UBUS = re.compile(r"^ubus call (\S+) (\S+)(?: '(.*)')?$")
_ASSIGN = re.compile(r"^(\w+)=\$\((uci .+)\)$")
_VAR = re.compile(r"\$(\w+)")
_RELOADS = frozenset(f"/etc/init.d/{s} reload" for s in ("dnsmasq", "odhcpd", "network"))
_ANONYMOUS = re.compile(r"cfg[0-9a-f]{6}")
HELP = (
    "switch0: mt7620(mt7620), ports: 8 (cpu @ 6), vlans: 16\n     --switch\n"
    "\tAttribute 1 (int): enable_vlan (VLAN mode (1:enabled))\n"
    "\tAttribute 2 (string): mib (Get MIB counters for switch)\n"
    "\tAttribute 3 (int): mirror_monitor_port (Mirror monitor port)\n"
    "\tAttribute 4 (string): arl_table (Get ARL table)\n"
    "\tAttribute 5 (none): apply (Activate changes in the hardware)\n"
    "\tAttribute 6 (none): reset (Reset the switch)\n     --vlan\n"
    "\tAttribute 1 (int): vid (VLAN ID (0-4094))\n\tAttribute 2 (ports): ports (VLAN port mapping)\n"
    "     --port\n\tAttribute 1 (string): mib (Get MIB counters for port)\n"
    "\tAttribute 2 (int): enable_mirror_rx (Enable mirroring of RX packets)\n"
    "\tAttribute 3 (int): enable_mirror_tx (Enable mirroring of TX packets)\n"
    "\tAttribute 4 (int): enable (Enable the external PHY)\n\tAttribute 5 (int): pvid (Primary VLAN ID)\n"
    "\tAttribute 6 (unknown): link (Get port link information)\n"
)
FEATURES = {
    "switch_title": "mt7620), ports: 8 (cpu @ 6",
    "num_vlans": "16",
    "min_vid": 1,
    "vlan_option": "enable_vlan",
    "vid_option": "vid",
    "mirror_option": "enable_mirror_rx",
}


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult("", stdout, "", 0)


def _fail(stderr: str, status: int = 1) -> CommandResult:
    return CommandResult("", "", stderr, status)


def _contents(uci: dict[str, str]) -> dict[str, tuple[str, tuple[tuple[str, str], ...]]]:
    """{config.section: (type, its options)}."""
    out: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
        k: (v, ()) for k, v in uci.items() if k.count(".") == 1
    }
    for key, value in uci.items():
        if key.count(".") == 2:
            section = key.rsplit(".", 1)[0]
            type_, options = out.get(section, ("", ()))
            out[section] = (type_, (*options, (key.rsplit(".", 1)[1], value)))
    return out


def _libuci_names(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """libuci names an unnamed section from its type and options each time it loads a config, so once a
    change is committed an edited or new one has another name (the app must not count on the old one)."""
    old, new = _contents(before), _contents(after)
    renamed = {
        section: f"{section.split('.')[0]}.cfg{hashlib.sha1(repr(content).encode()).hexdigest()[:6]}"
        for section, content in new.items()
        if _ANONYMOUS.fullmatch(section.split(".")[1]) and old.get(section) != content
    }
    if not renamed:
        return after
    out: dict[str, str] = {}
    for key, value in after.items():
        section = ".".join(key.split(".")[:2])
        out[renamed.get(section, section) + key[len(section) :]] = value
    return out


def _render(uci: dict[str, str], config: str) -> str:
    """`uci -X show <config>`: each section, then its options."""
    lines: list[str] = []
    for name in [k for k in uci if k.startswith(config + ".") and k.count(".") == 1]:
        lines.append(f"{name}={uci[name]}")
        lines += [
            f"{k}={shell_quote(v)}" for k, v in uci.items() if k.startswith(name + ".") and k.count(".") == 2
        ]
    return "\n".join(lines) + ("\n" if lines else "")


class SimNetwork:
    def __init__(
        self,
        uci_text: str,
        *,
        pc_ip: str = "192.168.1.10",
        pc_port: int = 3,
        clock: Callable[[], float] = time.monotonic,
        leases: Sequence[tuple[str, str, str]] = (),
        wifi_mirror: bool = False,
        arl: dict[str, int] | None = None,
    ) -> None:
        self._committed = parse_uci_show(uci_text)
        self._work: dict[str, dict[str, str]] = {}
        self._snapshot: dict[str, str] | None = None
        self._deadline: float | None = None
        self._apply_sid: str | None = None
        self._enabled = dict.fromkeys(EXTERNAL, True)
        conf = switch_conf(self._committed, SWITCH)
        self._monitor = (conf.mirror_monitor_port if conf else None) or 0  # the switch's live monitor port
        self._new = 0x1000A0
        self.pc_ip = pc_ip
        self.pc_port = pc_port
        self._clock = clock
        self._leases = list(leases)
        self._wifi_mirror = wifi_mirror
        self.arl = dict(arl or {})  # MAC → port in `get arl_table` (empty, as on AP2's mt7620)
        self.extra_links: set[int] = set()  # more switch ports with a link than the PC's
        self.fw: Any = None  # the SimFirewall of the same router, which may cut the PC's SSH
        self.modem: SimModem | None = None  # the LTE modem: its session is the qmi interface's state

    # ---------------------------------------------------------------- what the connector asks
    def _expire(self) -> None:
        if self._deadline is not None and self._clock() >= self._deadline:
            assert self._snapshot is not None
            self._committed = self._snapshot  # rpcd's rollback, then the reload it triggers
            self._snapshot = self._deadline = self._apply_sid = None
            self._reset_switch()

    def _lan(self) -> Any:
        return next((i for i in interfaces(self._committed) if i.name == "lan"), None)

    def address(self) -> str | None:
        self._expire()
        lan = self._lan()
        return lan.address.ip if lan is not None and lan.proto == "static" and lan.address else None

    def uci(self) -> dict[str, str]:
        """Every config as committed now (after a rollback that came due)."""
        self._expire()
        return dict(self._committed)

    def reachable(self) -> bool:
        """The PC reaches lan: its address is in lan's subnet, its switch port is on and in lan's VLAN,
        and the firewall lets its SSH in."""
        self._expire()
        if self.fw is not None:
            self.fw.fire(self.fw.dispatch)  # a rollback timer that came due runs, reachable or not
        if self.fw is not None and not self.fw.admits_ssh(self.pc_ip):
            return False
        lan = self._lan()
        if lan is None or lan.address is None or not self._enabled.get(self.pc_port, True):
            return False
        network = ipaddress.ip_interface(str(lan.address)).network
        if ipaddress.ip_address(self.pc_ip) not in network:
            return False
        vlans = switch_vlans(self._committed)
        if not vlans:
            return True
        bridge = next((d for d in devices(self._committed) if d.name == lan.device), None)
        ports = bridge.ports if bridge is not None else (lan.device or "",)
        vids = {
            int(p.rsplit(".", 1)[1]) for p in ports if p.startswith("eth0.") and p.rsplit(".", 1)[1].isdigit()
        }
        return any(v.vlan in vids and (self.pc_port, False) in v.members for v in vlans)

    # ---------------------------------------------------------------- entry point
    def answer(self, command: str) -> CommandResult | None:
        self._expire()
        if "\n" not in command:
            return self._one(command.strip(), {})
        saved = {k: dict(v) for k, v in self._work.items()}
        committed = dict(self._committed)
        out: list[str] = []
        names: dict[str, str] = {}
        for line in command.split("\n"):
            line = line.strip()
            if not line or line == "set -e":
                continue
            result = self._line(line, names)
            if result is None or not result.ok:
                self._work, self._committed = saved, committed  # nothing half-staged
                return (
                    None
                    if result is None
                    else CommandResult(command, "".join(out), result.stderr, result.exit_status)
                )
            out.append(result.stdout)
        return CommandResult(command, "".join(out), "", 0)

    def _line(self, line: str, names: dict[str, str]) -> CommandResult | None:
        if m := _ASSIGN.match(line):
            result = self._one(m.group(2), names)
            if result is not None and result.ok:
                names[m.group(1)] = result.stdout.strip()
            return result
        return self._one(line, names)

    def _one(self, p: str, names: dict[str, str]) -> CommandResult | None:
        p = _VAR.sub(lambda m: names.get(m.group(1), m.group(0)), p)
        if p.startswith("uci "):
            return self._uci(p)
        if p.startswith("mkdir -p /var/run/rpcd/uci-"):
            return _ok()
        if p in _RELOADS:
            if p.endswith("network reload"):
                self._reset_switch()
            return _ok()
        if p == 'echo "$SSH_CONNECTION"':
            return _ok(f"{self.pc_ip} 50000 {self.address()} 22\n")
        if p == "cat /proc/net/arp":
            head = "IP address       HW type     Flags       HW address            Mask     Device\n"
            return _ok(head + f"{self.pc_ip:<16} 0x1         0x2         {PC_MAC}     *        br-lan\n")
        if m := re.fullmatch(r"ip -j -([46]) (route show table all|rule show)", p):
            family = int(m.group(1))
            body = self._routes(family) if m.group(2).startswith("route") else self._rules(family)
            return _ok(json.dumps(body) + "\n")
        if m := re.fullmatch(rf"swconfig dev {SWITCH} (.+)", p):
            return self._swconfig(m.group(1))
        if m := _UBUS.match(p):
            return self._ubus(m.group(1), m.group(2), json.loads(m.group(3) or "{}"))
        return None

    # ---------------------------------------------------------------- uci
    def _view(self, savedir: str) -> dict[str, str]:
        return self._work.get(savedir, self._committed)

    def _staged(self, savedir: str) -> dict[str, str]:
        if savedir not in self._work:
            self._work[savedir] = dict(self._committed)
        return self._work[savedir]

    def _uci(self, p: str) -> CommandResult | None:
        tokens = shlex.split(p)[1:]
        savedir = DEFAULT
        while tokens and tokens[0].startswith("-"):
            flag = tokens.pop(0)
            if flag == "-P" and tokens:
                savedir = tokens.pop(0)
        if not tokens:
            return _fail("Usage: uci [<options>] <command> [<arguments>]\n")
        verb, args = tokens[0], tokens[1:]
        if not args:
            return None  # `uci show` of every config: the Wi-Fi simulator answers it
        config = args[0].split(".", 1)[0].split("=", 1)[0]
        if config not in CONFIGS:  # another config (wireless) is someone else's; a malformed line fails
            bare = verb in ("show", "commit", "add")
            ours = bool(args) and re.fullmatch(r"[a-z0-9_]+", config) is not None and (bare or "." in args[0])
            return None if ours else _fail("uci: Invalid argument\n")
        if verb == "show":
            return _ok(_render(self._view(savedir), config))
        if verb == "commit":
            work = self._work.pop(savedir, None)
            if work is not None:
                kept = {k: v for k, v in self._committed.items() if not k.startswith(config + ".")}
                now = kept | {k: v for k, v in work.items() if k.startswith(config + ".")}
                self._committed = _libuci_names(self._committed, now)
            return _ok()
        if verb == "add" and len(args) == 2:
            name = f"cfg{self._new:06x}"
            self._new += 1
            self._staged(savedir)[f"{config}.{name}"] = args[1]
            return _ok(name + "\n")
        if len(args) != 1:
            return _fail("uci: Invalid argument\n")
        return self._change(self._staged(savedir), verb, args[0])

    @staticmethod
    def _change(work: dict[str, str], verb: str, arg: str) -> CommandResult:
        path, eq, value = arg.partition("=")
        section = ".".join(path.split(".")[:2])
        if verb == "delete":
            found = [k for k in work if k == path or k.startswith(path + ".")]
            if not found:  # uci exits 1 on a missing entry, -q only hides the message (AP2, 2026-11-07)
                return _fail("uci: Entry not found\n")
            for key in found:
                del work[key]
            return _ok()
        if not eq or (path.count(".") == 2 and section not in work):
            return _fail("uci: Invalid argument\n")
        items = work.get(path, "").split()
        if verb == "set":
            work[path] = value
        elif verb == "add_list":
            work[path] = " ".join([*items, value])
        elif verb == "del_list":
            kept = [i for i in items if i != value]
            if kept:
                work[path] = " ".join(kept)
            else:
                work.pop(path, None)
        else:
            return _fail("uci: Invalid argument\n")
        return _ok()

    # ---------------------------------------------------------------- ubus
    def _ubus(self, obj: str, method: str, args: dict[str, Any]) -> CommandResult | None:
        if obj == "uci" and method in ("apply", "confirm"):
            return self._apply(args) if method == "apply" else self._confirm(args)
        if (obj, method) == ("uci", "get") and args.get("config") in CONFIGS:
            return self._uci_get(str(args["config"]), args.get("section"))
        if (obj, method) == ("network.interface", "dump"):
            return _ok(json.dumps({"interface": self._dump()}, indent="\t") + "\n")
        if obj.startswith("network.interface.") and method == "status":
            entry = next(
                (i for i in self._dump() if i["interface"] == obj.removeprefix("network.interface.")), None
            )
            if entry is None:
                return _fail("Command failed: Not found\n", 4)
            return _ok(json.dumps({k: v for k, v in entry.items() if k != "interface"}, indent="\t") + "\n")
        if (obj, method) == ("network.device", "status"):
            if "name" in args:  # one device: netifd answers with that device's object itself
                found = self._devices().get(str(args["name"]))
                if found is None:
                    return _fail("Command failed: Not found\n", 4)
                return _ok(json.dumps(found, indent="\t") + "\n")
            return _ok(json.dumps(self._devices(), indent="\t") + "\n")
        if (obj, method) == ("luci-rpc", "getDHCPLeases"):
            leases = [
                {"expires": 43000, "hostname": name, "macaddr": mac.upper(), "ipaddr": ip}
                for name, mac, ip in self._leases
            ]
            return _ok(json.dumps({"dhcp_leases": leases, "dhcp6_leases": []}, indent="\t") + "\n")
        if (obj, method) == ("luci", "getSwconfigFeatures") and args.get("switch") == SWITCH:
            return _ok(json.dumps(FEATURES, indent="\t") + "\n")
        if (obj, method) == ("service", "list"):
            return _ok(json.dumps(self._service(str(args.get("name", ""))), indent="\t") + "\n")
        return None

    def _apply(self, args: dict[str, Any]) -> CommandResult:
        sid = str(args.get("ubus_rpc_session", ""))
        rollback = bool(args.get("rollback"))
        if rollback and self._deadline is not None:
            return _fail("Command failed: Permission denied\n", 6)
        work = self._work.pop(f"/var/run/rpcd/uci-{sid}", None)
        if work is None:
            return _fail("Command failed: No data\n", 5)
        network_changed = any(
            self._committed.get(k) != work.get(k)
            for k in {*self._committed, *work}
            if k.startswith("network.")
        )
        if rollback:
            self._snapshot = dict(self._committed)
            self._deadline = self._clock() + int(args.get("timeout", 30))
            self._apply_sid = sid
        self._committed = _libuci_names(self._committed, work)
        if network_changed:
            self._reset_switch()  # the network reload re-applies the switch config
        return _ok()

    def _uci_get(self, config: str, section: Any) -> CommandResult:
        """rpcd's `uci get`: one section's values (with .type and .name); the status poller reads dhcp.lan."""
        name = f"{config}.{section}"
        if name not in self._committed:
            return _fail("Command failed: Not found\n", 4)
        values: dict[str, Any] = {".type": self._committed[name], ".name": str(section)}
        for key, value in self._committed.items():
            if key.startswith(name + ".") and key.count(".") == 2:
                values[key.rsplit(".", 1)[1]] = value
        return _ok(json.dumps({"values": values}, indent="\t") + "\n")

    def _confirm(self, args: dict[str, Any]) -> CommandResult:
        if self._deadline is None or args.get("ubus_rpc_session") != self._apply_sid:
            return _fail("Command failed: No data\n", 5)
        self._snapshot = self._deadline = self._apply_sid = None
        return _ok()

    def _service(self, name: str) -> dict[str, Any]:
        running = {"running": True, "pid": 2625}
        if name == "dnsmasq":
            return {"dnsmasq": {"instances": {"cfg01411c": running}}}
        if name == "wifi-mirror" and self._wifi_mirror:
            return {"wifi-mirror": {"instances": {"instance1": running}}}
        return {}

    # ---------------------------------------------------------------- network state
    def _dump(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for conf in interfaces(self._committed):
            session = self.modem.connected if self.modem is not None else True
            entry: dict[str, Any] = {
                "interface": conf.name,
                "up": conf.auto and (conf.proto in ("static", "none") or (conf.proto == "qmi" and session)),
                "pending": conf.proto in ("dhcp", "dhcpv6"),
                "dynamic": False,
                "proto": conf.proto,
                "ipv4-address": [],
                "ipv6-address": [],
            }
            device = "wwan0" if conf.proto == "qmi" else conf.device
            if device:
                entry["device"] = device
                entry["l3_device"] = device
            if entry["up"]:
                entry["uptime"] = 1000
                if conf.proto == "static" and conf.address is not None:
                    entry["ipv4-address"] = [{"address": conf.address.ip, "mask": conf.address.prefix}]
            out.append(entry)
            if conf.proto == "qmi":
                leased = bool(entry["up"]) and self.modem is not None and self.modem.lease
                dynamic: dict[str, Any] = {
                    "interface": f"{conf.name}_4",
                    "up": leased,
                    "pending": bool(entry["up"]) and not leased,
                    "dynamic": True,
                    "proto": "dhcp",
                    "device": "wwan0",
                    "ipv4-address": [{"address": "10.64.12.7", "mask": 30}] if leased else [],
                }
                if leased:
                    dynamic["uptime"] = 990
                    dynamic["l3_device"] = "wwan0"
                out.append(dynamic)
        return out

    def _devices(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for d in devices(self._committed):
            out[d.name] = {"type": d.type or "Network device", "up": True, "bridge-members": list(d.ports)}
        for v in switch_vlans(self._committed):
            out.setdefault(f"eth0.{v.vid or v.vlan}", {"type": "VLAN", "up": True})
        if self.modem is not None and any(i.proto == "qmi" for i in interfaces(self._committed)):
            out["wwan0"] = {
                "type": "Network device",
                "up": self.modem.connected,
                "mtu": 1420,
                "statistics": {"rx_bytes": self.modem.rx_bytes, "tx_bytes": self.modem.tx_bytes},
            }
        for name, d in out.items():  # the MACs AP2 reports (tests/fixtures/ap2/network.json)
            d["macaddr"] = DEVICE_MACS.get(name, "00:0c:43:76:20:77")
        return out

    def _l3(self, name: str | None) -> str | None:
        entry = next((i for i in self._dump() if i["interface"] == name and i["up"]), None)
        return entry.get("l3_device") if entry else None

    def _routes(self, family: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if family == 4:
            for entry in self._dump():
                for a in entry["ipv4-address"] if entry["up"] else []:
                    net = ipaddress.ip_interface(f"{a['address']}/{a['mask']}").network
                    out.append(
                        {
                            "dst": str(net),
                            "dev": entry["l3_device"],
                            "protocol": "kernel",
                            "scope": "link",
                            "prefsrc": a["address"],
                        }
                    )
        kind = "route" if family == 4 else "route6"
        for r in routes(self._committed):
            dev = self._l3(r.interface)
            if r.kind != kind or r.disabled or dev is None:
                continue
            route: dict[str, Any] = {"dst": r.target, "dev": dev, "protocol": "static"}
            if r.gateway:
                route["gateway"] = r.gateway
            if r.metric is not None:
                route["metric"] = r.metric
            if r.table:
                route["table"] = r.table
            out.append(route)
        return out

    def _rules(self, family: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"priority": 0, "src": "all", "table": "local"}]
        kind = "rule" if family == 4 else "rule6"
        for r in rules(self._committed):
            if r.kind != kind or r.disabled:
                continue
            rule: dict[str, Any] = {"priority": r.priority if r.priority is not None else 30000, "src": "all"}
            if r.src:
                ip, _, bits = r.src.partition("/")
                rule["src"] = ip
                if bits:
                    rule["srclen"] = int(bits)
            if r.lookup:
                rule["table"] = r.lookup
            out.append(rule)
        out += [
            {"priority": 32766, "src": "all", "table": "main"},
            {"priority": 32767, "src": "all", "table": "default"},
        ]
        return out

    # ---------------------------------------------------------------- switch
    def _reset_switch(self) -> None:
        self._enabled = dict.fromkeys(EXTERNAL, True)  # swconfig reset on every network reload
        # A reload sets the monitor port only when the config names one; otherwise the switch keeps the one
        # it has (AP2, 2026-11-06: 1 stayed after mirror_monitor_port left the config).
        conf = switch_conf(self._committed, SWITCH)
        if conf is not None and conf.mirror_monitor_port is not None:
            self._monitor = conf.mirror_monitor_port

    def _swconfig(self, rest: str) -> CommandResult:
        if rest == "help":
            return _ok(HELP)
        if rest == "get arl_table":
            lines = "".join(f"Port {port}: MAC {mac}\n" for mac, port in self.arl.items())
            return _ok("address resolution table\n" + lines + "\n")
        if rest == "show":
            return _ok(self._show())
        if m := re.fullmatch(r"port (\d+) set enable ([01])", rest):
            port = int(m.group(1))
            if port not in EXTERNAL:
                return _fail("Failed to set attribute: invalid port\n")
            self._enabled[port] = m.group(2) == "1"
            return _ok()
        if m := re.fullmatch(r"set mirror_monitor_port (\d+)", rest):
            self._monitor = int(m.group(1))
            return _ok()
        return _fail("Unknown command\n")

    def _show(self) -> str:
        mirror = {p.port: p for p in switch_ports(self._committed)}
        vlans = switch_vlans(self._committed)
        lines = [
            "Global attributes:",
            "\tenable_vlan: 1",
            f"\tmirror_monitor_port: {self._monitor}",
        ]
        for port in range(PORTS):
            sp = mirror.get(port)
            pvid = next((v.vid or v.vlan for v in vlans if (port, False) in v.members), 0)
            enable = ("1" if self._enabled[port] else "0") if port in EXTERNAL else "???"
            linked = port == self.pc_port or port in self.extra_links
            up = (linked and self._enabled.get(port, False)) or port == CPU
            speed = "1000" if port == CPU else "100"
            link = f"port:{port} link:up speed:{speed}baseT full-duplex " if up else f"port:{port} link:down"
            lines += [
                f"Port {port}:",
                f"\tenable_mirror_rx: {int(bool(sp and sp.mirror_rx))}",
                f"\tenable_mirror_tx: {int(bool(sp and sp.mirror_tx))}",
                f"\tenable: {enable}",
                f"\tpvid: {pvid}",
                f"\tlink: {link}",
            ]
        for v in vlans:
            lines += [
                f"VLAN {v.vlan}:",
                f"\tvid: {v.vid or v.vlan}",
                f"\tports: {render_members(dict(v.members))} ",
            ]
        return "\n".join(lines) + "\n"
