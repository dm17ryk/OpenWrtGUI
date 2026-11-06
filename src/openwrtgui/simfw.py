"""The simulated firewall: fw4's ruleset rendered from the `firewall` config SimNetwork holds (so rpcd's
staging, apply, confirm and rollback work unchanged), runtime nft tables, tc qdiscs and filters, conntrack,
router-side timers, the app's /tmp/owg files, custom rule files and a tcpdump stream. It answers the exact
command shapes the Firewall and Faults screens send; anything else is left to the other simulators."""

from __future__ import annotations

import copy
import fnmatch
import ipaddress
import json
import re
import shlex
import struct
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openwrtgui.fw.commands import CUSTOM_FILES
from openwrtgui.fw.model import FirewallConf, FwRuleConf, ZoneConf
from openwrtgui.fw.nft import zone_tail
from openwrtgui.fw.parse import firewall_conf
from openwrtgui.transport.base import CommandResult

if TYPE_CHECKING:
    from openwrtgui.simnet import SimNetwork

Dispatch = Callable[[str], CommandResult | None]

SSH_PORT = 22
OWNED = ("/tmp/", "/etc/nftables.d/", "/etc/owg/")  # files this simulator keeps; others are recorded
NO_SUCH = "Error: Could not process rule: No such file or directory\n"
GATED = frozenset({"netdev", "bridge"})  # families a router may lack (kmod-nft-netdev, kmod-nft-bridge)
DEVICES = ("lo", "eth0", "eth0.1", "eth0.2", "br-lan", "phy0-ap0", "wwan0")
DEFAULT_ROOT = {"eth0": ("fq_codel", "limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms")}
IMAGE_CUSTOM = {
    "/etc/nftables.d/10-custom-filter-chains.nft": (
        "## The following chains are examples; they are not loaded by default.\n"
        "# chain user_pre_input {\n#\ttype filter hook input priority -1; policy accept;\n# }\n"
    )
}
MODULES = (
    "act_mirred.ko",
    "cls_u32.ko",
    "ifb.ko",
    "nf_conntrack.ko",
    "nf_tables.ko",
    "nft_numgen.ko",
    "sch_netem.ko",
    "sch_prio.ko",
)
TOOLS = "".join(
    f"{path}\n"
    for path in (
        "/sbin/start-stop-daemon",
        "/usr/bin/setsid",
        "/usr/bin/timeout",
        "/usr/sbin/tcpdump",
        "/usr/sbin/conntrack",
        "/sbin/fw4",
    )
)
_PRIORITY = {"raw": -300, "mangle": -150, "dstnat": -100, "filter": 0, "security": 50, "srcnat": 100}
_DECL = re.compile(r'type (\S+) hook (\S+)(?: device "([^"]+)")? priority (\S+);(?: policy (\S+);)?')
_COMMENT = re.compile(r'comment "([^"]*)"')
_JUMP = re.compile(r"(?:^|\s)(?:jump|goto) (\S+)$")
_HEREDOC = re.compile(r"(.*?) <<'OWG'\n(.*)\nOWG", re.S)
_RECORD = re.compile(r"""printf '%s"armed_at":%s}\\n' ('(?:[^']|'\\'')*') "\$\(date \+%s\)" > (\S+)""")


@dataclass
class _Rule:
    text: str

    @property
    def comment(self) -> str | None:
        m = _COMMENT.search(self.text)
        return m.group(1) if m else None

    @property
    def jump(self) -> str | None:
        m = _JUMP.search(self.text)
        return m.group(1) if m else None


@dataclass
class _Chain:
    name: str
    decl: str | None = None
    rules: list[_Rule] = field(default_factory=list)

    def hook(self) -> dict[str, Any]:
        m = _DECL.match(self.decl or "")
        if not m:
            return {}
        type_, hook, device, prio, policy = m.groups()
        out: dict[str, Any] = {
            "type": type_,
            "hook": hook,
            "prio": int(prio) if prio.lstrip("-").isdigit() else _PRIORITY.get(prio, 0),
            "policy": policy or "accept",
        }
        if device:
            out["dev"] = device
        return out


@dataclass
class _Table:
    family: str
    name: str
    sets: list[str] = field(default_factory=list)  # raw blocks, one statement per line
    chains: list[_Chain] = field(default_factory=list)

    def chain(self, name: str) -> _Chain | None:
        return next((c for c in self.chains if c.name == name), None)


class NftError(Exception):
    pass


# ------------------------------------------------------------------ a small nft script parser
def _uncomment(text: str) -> str:
    """Each line up to a `#` outside quotes (an nft comment)."""
    lines = []
    for line in text.split("\n"):
        quoted = False
        for i, ch in enumerate(line):
            if ch == '"':
                quoted = not quoted
            elif ch == "#" and not quoted:
                line = line[:i]
                break
        lines.append(line)
    return "\n".join(lines)


def _split(text: str) -> list[str]:
    """Statements of an nft script: split at newlines and `;` outside braces and quotes."""
    text = _uncomment(text)
    out: list[str] = []
    cur: list[str] = []
    depth, quoted = 0, False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "{":
            depth += 1
        elif not quoted and ch == "}":
            depth -= 1
            if depth < 0:
                raise NftError("Error: syntax error, unexpected '}'\n")
        if not quoted and depth == 0 and ch in "\n;":
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if depth != 0 or quoted:
        raise NftError("Error: syntax error, unexpected end of file\n")
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip() and not s.strip().startswith("#")]


def _body(statement: str, head: str) -> tuple[str, str] | None:
    """`<head> NAME { BODY }` → (NAME, BODY)."""
    m = re.fullmatch(rf"{head} (\S+)\s*\{{(.*)\}}", statement, re.S)
    return (m.group(1), m.group(2)) if m else None


def _clean(rule: str) -> str:
    return re.sub(r"counter packets \d+ bytes \d+", "counter", re.sub(r"\s+# handle \d+$", "", rule.strip()))


def _chain_from(name: str, body: str) -> _Chain:
    decl: list[str] = []
    rules: list[_Rule] = []
    for s in _split(body):
        if s.startswith(("type ", "policy ")):
            decl.append(s + ";")
        else:
            rules.append(_Rule(_clean(s)))
    return _Chain(name, " ".join(decl) or None, rules)


class SimFirewall:
    def __init__(
        self,
        net: SimNetwork,
        runtime: Mapping[str, Any],
        *,
        families: frozenset[str] = GATED,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._net = net
        net.fw = self
        self._families = families
        self._clock = clock
        self._fw4_chains = [
            _Chain(name, None, [_Rule(r) for r in rules])
            for name, rules in runtime.get("fw4_chains", {}).items()
        ]
        self._tables: list[_Table] = []
        for text in runtime.get("tables", []):
            self._script(str(text), self._tables)
        self._conntrack: list[str] = list(runtime.get("conntrack", []))
        self._tc_tables: list[str] = list(runtime.get("tc_tables", []))
        self._rom_custom = sorted(IMAGE_CUSTOM)
        self._files: dict[str, str] = dict(IMAGE_CUSTOM)
        self._timers: dict[str, tuple[float, list[str]]] = {}  # pid file -> (fires at, lines)
        self._root: dict[str, tuple[str, str, str]] = {}  # dev -> (kind, handle, params) when not default
        self._children: dict[
            str, list[tuple[str, str, str, str]]
        ] = {}  # dev -> (kind, handle, parent, params)
        self._ingress: set[str] = set()
        self._filters: dict[tuple[str, str], list[str]] = {}  # (dev, parent) -> `match … ` lines
        self._links: set[str] = set()
        self.dispatch: Dispatch = self.answer

    # ---------------------------------------------------------------- what the network asks
    def admits_ssh(self, pc_ip: str) -> bool:
        """The PC's SSH reaches the router: the own zone (lan's) accepts it, and no runtime input chain
        drops it."""
        conf = firewall_conf(self._net.uci())
        zone = next((z for z in conf.zones if "lan" in z.networks), None)
        if (
            zone is not None
            and zone.input != "ACCEPT"
            and not any(_accepts_ssh(r, zone, pc_ip) for r in conf.rules)
        ):
            return False
        for table in self._tables:
            for c in table.chains:
                hook = c.hook()
                if hook.get("hook") in ("input", "prerouting", "ingress") and hook.get("policy") == "drop":
                    return False
        return True

    # ---------------------------------------------------------------- timers
    def fire(self, dispatch: Dispatch) -> None:
        now = self._clock()
        for pid, (at, lines) in list(self._timers.items()):
            if now >= at:
                del self._timers[pid]
                self._files.pop(pid, None)
                for line in lines:
                    dispatch(line)

    # ---------------------------------------------------------------- entry point
    def answer(self, command: str) -> CommandResult | None:
        if m := _HEREDOC.fullmatch(command):
            return self._heredoc(command, m.group(1).strip(), m.group(2))
        if command == CUSTOM_FILES:  # one command, though it holds ; and &&
            return self._plain(command)
        parts = _parts(command)
        if len(parts) == 1 and parts[0][0] == command.strip():
            return self._one(command.strip())
        out: list[str] = []
        status = 0
        for part, joiner in parts:
            if part == "set -e":
                continue
            r = self.dispatch(part)
            if r is None:
                return None
            out.append(r.stdout)
            status = r.exit_status
            if not r.ok and (joiner == "&&" or "set -e" in command.split("\n", 1)[0]):
                return CommandResult(command, "".join(out), r.stderr, r.exit_status)
        return CommandResult(command, "".join(out), "", status)

    def _heredoc(self, command: str, head: str, text: str) -> CommandResult | None:
        if head in ("nft -f /dev/stdin", "nft -c -f /dev/stdin"):
            return self._nft_script(command, text, check=" -c " in f" {head} ")
        if m := re.fullmatch(r"cat > (\S+)", head):
            self._files[m.group(1)] = text + "\n"
            return _ok(command)
        return None

    def _one(self, p: str) -> CommandResult | None:
        quiet = p.endswith(" 2>/dev/null")
        if quiet:
            p = p.removesuffix(" 2>/dev/null")
        if m := re.fullmatch(r"(.+?) > (/tmp/\S+)", p):
            if _RECORD.fullmatch(p):
                return self._record(p)
            r = self.dispatch(m.group(1))
            if r is None:
                return None
            if r.ok:
                self._files[m.group(2)] = r.stdout
            return CommandResult(p, "", r.stderr, r.exit_status)
        r = self._plain(p)
        if r is not None and quiet:
            return CommandResult(p, r.stdout, "", r.exit_status)
        return r

    def _plain(self, p: str) -> CommandResult | None:  # noqa: PLR0911 - one branch per command shape
        if p.startswith("nft "):
            return self._nft(p)
        if p.startswith("tc "):
            return self._tc(p)
        if p.startswith("start-stop-daemon "):
            return self._daemon(p)
        if p == "fw4 print":
            return _ok(p, self._fw4_print())
        if p in ("fw4 reload", "fw4 -q reload") or (p.startswith("mkdir -p ") and p[9:].startswith(OWNED)):
            return _ok(p)
        if p == "conntrack -L -p udp":
            n = len(self._conntrack)
            footer = f"conntrack v1.4.8 (conntrack-tools): {n} flow entries have been shown.\n"
            return CommandResult(p, "".join(line + "\n" for line in self._conntrack), footer, 0)
        if p == "ls /usr/lib/tc":
            if not self._tc_tables:
                return CommandResult(p, "", "ls: /usr/lib/tc: No such file or directory\n", 1)
            return _ok(p, "\n".join(self._tc_tables) + "\n")
        if p == "ls /lib/modules/$(uname -r)":
            return _ok(p, "\n".join(MODULES) + "\n")
        if p == "ls /rom/etc/nftables.d":
            return _ok(p, "".join(name.rsplit("/", 1)[1] + "\n" for name in self._rom_custom))
        if p.startswith("command -v "):
            return _ok(p, TOOLS)
        if p == 'for f in /etc/nftables.d/*.nft; do [ -e "$f" ] && { echo "=== $f"; cat "$f"; }; done':
            files = sorted(f for f in self._files if fnmatch.fnmatch(f, "/etc/nftables.d/*.nft"))
            return _ok(p, "".join(f"=== {f}\n{self._files[f]}" for f in files))
        if p == "date +%s":
            return _ok(p, f"{int(self._clock())}\n")
        if m := re.fullmatch(r'kill -0 "\$\(cat (\S+)\)"', p):
            alive = m.group(1) in self._timers
            return CommandResult(p, "", "" if alive else "kill: No such process\n", 0 if alive else 1)
        if m := re.fullmatch(r"ip link (add owgifb0 type ifb|set owgifb0 up|del owgifb0)", p):
            return self._ifb(p, m.group(1))
        return self._file(p)

    # ---------------------------------------------------------------- files
    def _file(self, p: str) -> CommandResult | None:
        tokens = p.split()
        if tokens[:1] == ["touch"] and len(tokens) == 2:
            self._files.setdefault(tokens[1], "")
            return _ok(p)
        if tokens[:1] == ["cat"] and len(tokens) == 2 and tokens[1].startswith(OWNED):
            names = sorted(f for f in self._files if fnmatch.fnmatch(f, tokens[1]))
            if not names:
                return CommandResult(p, "", f"cat: can't open '{tokens[1]}': No such file or directory\n", 1)
            return _ok(p, "".join(self._files[f] for f in names))
        if tokens[:2] == ["rm", "-f"] and all(t.startswith(OWNED) for t in tokens[2:]):
            for pattern in tokens[2:]:
                for name in [f for f in self._files if fnmatch.fnmatch(f, pattern)]:
                    del self._files[name]
            return _ok(p)
        if tokens[:1] == ["cp"] and len(tokens) == 3 and tokens[1].startswith(OWNED):
            if tokens[1] not in self._files:
                return CommandResult(p, "", f"cp: can't stat '{tokens[1]}': No such file or directory\n", 1)
            self._files[tokens[2]] = self._files[tokens[1]]
            return _ok(p)
        return None

    def _record(self, p: str) -> CommandResult:
        m = _RECORD.fullmatch(p)
        assert m is not None
        self._files[m.group(2)] = f'{shlex.split(m.group(1))[0]}"armed_at":{int(self._clock())}}}\n'
        return _ok(p)

    # ---------------------------------------------------------------- start-stop-daemon (timers)
    def _daemon(self, p: str) -> CommandResult:
        tokens = shlex.split(p)
        pid = tokens[tokens.index("-p") + 1] if "-p" in tokens else ""
        if "-K" in tokens:
            if pid not in self._timers:
                return CommandResult(p, "", "", 1)
            del self._timers[pid]
            return _ok(p)
        script = tokens[tokens.index("-c") + 1]
        steps = [s.strip() for s in script.split("; ")]
        seconds = int(steps[0].split()[1]) if steps and steps[0].startswith("sleep ") else 0
        self._timers[pid] = (self._clock() + seconds, steps[1:])
        self._files[pid] = "4242\n"
        return _ok(p)

    # ---------------------------------------------------------------- nft
    def _nft(self, p: str) -> CommandResult | None:
        if p == "nft list tables":
            return _ok(p, "".join(f"table {t.family} {t.name}\n" for t in [self._fw4(), *self._tables]))
        if p in ("nft -j list ruleset", "nft -a list ruleset", "nft list ruleset"):
            tables = [self._fw4(), *self._tables]
            if p.startswith("nft -j"):
                return _ok(p, json.dumps({"nftables": _json(tables)}) + "\n")
            return _ok(p, "".join(_text(t, handles=p.startswith("nft -a")) for t in tables))
        if m := re.fullmatch(r"nft( -a| -j)? list (table|chain) (\S+) (\S+)(?: (\S+))?", p):
            flag, kind, family, name, chain = m.groups()
            table = (
                self._fw4() if (family, name) == ("inet", "fw4") else self._find(self._tables, family, name)
            )
            if table is None or (kind == "chain" and (chain is None or table.chain(chain) is None)):
                return CommandResult(p, "", NO_SUCH, 1)
            if kind == "chain":
                assert chain is not None
                table = _Table(table.family, table.name, [], [c for c in table.chains if c.name == chain])
            if flag == " -j":
                return _ok(p, json.dumps({"nftables": _json([table])}) + "\n")
            return _ok(p, _text(table, handles=flag == " -a"))
        if m := re.fullmatch(r"nft( -c)? -f (/tmp/\S+)", p):
            if m.group(2) not in self._files:
                return CommandResult(p, "", f'Error: Could not open file "{m.group(2)}"\n', 1)
            return self._nft_script(p, self._files[m.group(2)], check=bool(m.group(1)))
        if p.startswith("nft "):
            return self._nft_script(p, p.removeprefix("nft "), check=False)
        return None

    def _nft_script(self, command: str, text: str, *, check: bool) -> CommandResult:
        work = copy.deepcopy(self._tables)
        fw4 = copy.deepcopy(self._fw4_chains)
        try:
            self._script(text, work, fw4)
        except NftError as exc:
            return CommandResult(command, "", str(exc), 1)
        if not check:
            self._tables, self._fw4_chains = work, fw4
        return _ok(command)

    def _find(self, tables: Sequence[_Table], family: str, name: str) -> _Table | None:
        return next((t for t in tables if (t.family, t.name) == (family, name)), None)

    def _script(self, text: str, tables: list[_Table], fw4: list[_Chain] | None = None) -> None:
        for s in _split(text):
            self._statement(s, tables, fw4 if fw4 is not None else self._fw4_chains)

    def _family(self, family: str) -> None:
        if family in GATED and family not in self._families:
            raise NftError(NO_SUCH)

    def _statement(self, s: str, tables: list[_Table], fw4: list[_Chain]) -> None:  # noqa: PLR0912
        words = s.split()
        verb = words[0] if words else ""
        if verb in ("add", "create", "insert", "delete", "flush"):
            words = words[1:]
        kind = words[0] if words else ""
        if kind == "table" and len(words) >= 3:
            family, name = words[1], words[2]
            self._family(family)
            if (family, name) == ("inet", "fw4"):
                return  # fw4's table is rendered from the config; nothing to keep
            table = self._find(tables, family, name)
            if verb == "delete":
                if table is None:
                    raise NftError(NO_SUCH)
                tables.remove(table)
                return
            if verb == "flush":
                if table is None:
                    raise NftError(NO_SUCH)
                for c in table.chains:
                    c.rules.clear()
                return
            if table is None:
                table = _Table(family, name)
                tables.append(table)
            block = _body(s.split(" ", 1)[1] if verb in ("add", "create") else s, f"table {family}")
            if block:
                self._table_body(table, block[1])
            return
        if kind in ("chain", "rule") and len(words) >= 4:
            family, tname, cname = words[1], words[2], words[3]
            self._family(family)
            if (family, tname) == ("inet", "fw4"):
                self._fw4_statement(verb, kind, cname, s, fw4)
                return
            table = self._find(tables, family, tname)
            if table is None:
                raise NftError(NO_SUCH)
            self._chain_statement(table, verb, kind, cname, s)
            return
        raise NftError(f"Error: syntax error, unexpected {kind or 'end of file'}\n")

    def _table_body(self, table: _Table, body: str) -> None:
        for item in _split(body):
            if chain := _body(item, "chain"):
                c = _chain_from(*chain)
                self._check_decl(table.family, c)
                existing = table.chain(c.name)
                if existing is None:
                    table.chains.append(c)
                else:
                    existing.decl = existing.decl or c.decl
                    existing.rules += c.rules
            elif m := re.fullmatch(r"(\S+) (\S+)\s*\{(.*)\}", item, re.S):
                lines = "\n".join(f"\t\t{x}" for x in _split(m.group(3)))
                table.sets.append(f"\t{m.group(1)} {m.group(2)} {{\n{lines}\n\t}}")
            else:
                raise NftError(f"Error: syntax error, unexpected {item.split()[0]}\n")

    def _check_decl(self, family: str, c: _Chain) -> None:
        if c.decl and family == "netdev" and 'device "' not in c.decl:
            raise NftError("Error: Missing `device' in this chain definition\n")

    def _chain_statement(self, table: _Table, verb: str, kind: str, cname: str, s: str) -> None:
        chain = table.chain(cname)
        if kind == "chain":
            if verb == "delete":
                if chain is None:
                    raise NftError(NO_SUCH)
                if chain.rules:
                    raise NftError("Error: Could not process rule: Device or resource busy\n")
                table.chains.remove(chain)
            elif verb == "flush":
                if chain is None:
                    raise NftError(NO_SUCH)
                chain.rules.clear()
            elif chain is None:
                block = _body(s.split(f" {table.name} ", 1)[1], "") if "{" in s else None
                c = _chain_from(cname, block[1]) if block else _Chain(cname)
                self._check_decl(table.family, c)
                table.chains.append(c)
            return
        if chain is None:
            raise NftError(NO_SUCH)
        body = s.split(f" {cname} ", 1)[1] if f" {cname} " in s else ""
        if not body:
            raise NftError("Error: syntax error, unexpected end of file\n")
        if verb == "insert":
            chain.rules.insert(0, _Rule(_clean(body)))
        else:
            chain.rules.append(_Rule(_clean(body)))

    def _fw4_statement(self, verb: str, kind: str, cname: str, s: str, fw4: list[_Chain]) -> None:
        chain = next((c for c in fw4 if c.name == cname), None)
        if chain is None:
            if kind == "chain" and verb in ("add", "create"):
                fw4.append(_Chain(cname))
            return  # the rendered chains: changed by fw4 reloads only
        if kind == "chain" and verb == "flush":
            chain.rules.clear()
        elif kind == "chain" and verb == "delete":
            fw4.remove(chain)
        elif kind == "rule":
            chain.rules.append(_Rule(_clean(s.split(f" {cname} ", 1)[1])))

    # ---------------------------------------------------------------- fw4 rendered from the config
    def _devices(self, networks: Sequence[str]) -> list[str]:
        uci = self._net.uci()
        devs: list[str] = []
        for n in networks:
            dev = uci.get(f"network.{n}.device")
            dev = "wwan0" if (dev or "").startswith("/dev/") else dev
            if dev and dev not in devs:
                devs.append(dev)
        return devs

    def _fw4(self) -> _Table:
        conf = firewall_conf(self._net.uci())
        t = _Table("inet", "fw4")
        base = {
            d: _Chain(d, f"type filter hook {d} priority filter; policy accept;")
            for d in ("input", "forward", "output")
        }
        base["input"].rules.append(_Rule('iif "lo" accept comment "!fw4: Accept traffic from loopback"'))
        t.chains += list(base.values())
        for z in conf.zones:
            devs = _set(self._devices(z.networks))
            if devs:
                base["input"].rules.append(_Rule(f"iifname {devs} jump input_{z.name}"))
                base["forward"].rules.append(_Rule(f"iifname {devs} jump forward_{z.name}"))
                base["output"].rules.append(_Rule(f"oifname {devs} jump output_{z.name}"))
            t.chains += _zone_chains(conf, z)
        t.chains += [
            _Chain(f"{p}_{w}_{z.name}", None, [_Rule(f"counter {p}")])
            for z in conf.zones
            for w in ("from", "to")
            for p in ("accept", "reject", "drop")
        ]
        t.chains.append(
            _Chain("dstnat", "type nat hook prerouting priority dstnat; policy accept;", _redirects(conf))
        )
        t.chains.append(
            _Chain("srcnat", "type nat hook postrouting priority srcnat; policy accept;", _nats(conf))
        )
        t.chains += copy.deepcopy(self._fw4_chains)
        t.sets = [
            f"\tset {s.name} {{\n\t\ttype {_set_type(s.match)}\n"
            + (f"\t\telements = {{ {', '.join(s.entries)} }}\n" if s.entries else "")
            + "\t}"
            for s in conf.ipsets
            if s.enabled and s.name
        ]
        return t

    def _fw4_print(self) -> str:
        text = _text(self._fw4(), handles=False)
        custom = "".join(
            self._files[f] for f in sorted(self._files) if fnmatch.fnmatch(f, "/etc/nftables.d/*.nft")
        )
        return text.rstrip("\n").removesuffix("}") + custom + "}\n"

    # ---------------------------------------------------------------- tc and the app's ifb
    def _ifb(self, p: str, what: str) -> CommandResult:
        if what.startswith("add"):
            if "owgifb0" in self._links:
                return CommandResult(p, "", "RTNETLINK answers: File exists\n", 2)
            self._links.add("owgifb0")
        elif what.startswith("del"):
            if "owgifb0" not in self._links:
                return CommandResult(p, "", 'Cannot find device "owgifb0"\n', 1)
            self._links.discard("owgifb0")
            self._root.pop("owgifb0", None)
        return _ok(p)

    def _tc(self, p: str) -> CommandResult | None:  # noqa: PLR0911
        devices = [*DEVICES, *sorted(self._links)]
        if p == "tc qdisc show" or (m := re.fullmatch(r"tc qdisc show dev (\S+)", p)):
            want = devices if p == "tc qdisc show" else [m.group(1)] if m else []
            return _ok(p, "".join(self._qdisc_lines(d) for d in want if d in devices))
        if m := re.fullmatch(r"tc filter show dev (\S+) parent (\S+)", p):
            return _ok(p, "".join(self._filters.get((m.group(1), m.group(2)), [])))
        if m := re.fullmatch(r"tc qdisc add dev (\S+) root handle (\S+) (\S+)\s*(.*)", p):
            dev, handle, kind, params = m.groups()
            if dev not in devices:
                return CommandResult(p, "", "Cannot find device\n", 1)
            if dev in self._root:
                return CommandResult(p, "", "Error: Exclusivity flag on, cannot modify.\n", 2)
            self._root[dev] = (kind, handle, params)
            return _ok(p)
        if m := re.fullmatch(r"tc qdisc add dev (\S+) parent (\S+) handle (\S+) (\S+)\s*(.*)", p):
            dev, parent, handle, kind, params = m.groups()
            self._children.setdefault(dev, []).append((kind, handle, parent, params))
            return _ok(p)
        if m := re.fullmatch(r"tc qdisc add dev (\S+) handle ffff: ingress", p):
            self._ingress.add(m.group(1))
            return _ok(p)
        if m := re.fullmatch(
            r"tc filter add dev (\S+) parent (\S+) protocol ip prio 1 u32 match ip (src|dst) (\S+)/32 (.+)", p
        ):
            dev, parent, field_, ip, action = m.groups()
            at = 12 if field_ == "src" else 16
            line = (
                f"filter parent {parent} protocol ip pref 1 u32 chain 0 fh 800::800 order 2048 key ht 800 "
                "bkt 0 "
                f"{action} not_in_hw\n  match {int(ipaddress.IPv4Address(ip)):08x}/ffffffff at {at}\n"
            )
            self._filters.setdefault((dev, parent), []).append(line)
            return _ok(p)
        if m := re.fullmatch(r"tc qdisc del dev (\S+) (root|ingress)", p):
            dev, which = m.groups()
            if which == "root":
                if dev not in self._root:
                    return CommandResult(p, "", "Error: Cannot delete qdisc with handle of zero.\n", 2)
                handle = self._root.pop(dev)[1]
                self._children.pop(dev, None)
                self._filters.pop((dev, handle), None)
            else:
                self._ingress.discard(dev)
                self._filters.pop((dev, "ffff:"), None)
            return _ok(p)
        return None

    def _qdisc_lines(self, dev: str) -> str:
        if dev in self._root:
            kind, handle, params = self._root[dev]
            root = f"qdisc {kind} {handle} dev {dev} root refcnt 2 {params}".rstrip()
        else:
            kind, params = DEFAULT_ROOT.get(dev, ("noqueue", ""))
            root = f"qdisc {kind} 0: dev {dev} root refcnt 2 {params}".rstrip()
        lines = [root]
        for kind, handle, parent, params in self._children.get(dev, []):
            lines.append(f"qdisc {kind} {handle} dev {dev} parent {parent} limit 1000 {params}".rstrip())
        if dev in self._ingress:
            lines.append(f"qdisc ingress ffff: dev {dev} parent ffff:fff1 ----------------")
        return "".join(line + "\n" for line in lines)

    # ---------------------------------------------------------------- capture
    def stream(self, command: str) -> bytes | None:
        m = re.match(r"(?:timeout \d+ )?tcpdump -i (\S+) ", command)
        if not m or m.group(1) not in (*DEVICES, "owgmon0"):
            return None
        header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1)
        frame = bytes.fromhex("ffffffffffff0200000000010800") + bytes(46)
        packets = b"".join(
            struct.pack("<IIII", int(self._clock()) + i, 0, len(frame), len(frame)) + frame for i in range(2)
        )
        return header + packets


# ------------------------------------------------------------------ helpers
def _ok(command: str, stdout: str = "") -> CommandResult:
    return CommandResult(command, stdout, "", 0)


def _parts(command: str) -> list[tuple[str, str]]:
    """Shell statements joined by newlines, `;` or `&&` outside single quotes: (statement, joiner before)."""
    out: list[tuple[str, str]] = []
    cur: list[str] = []
    quoted = False
    joiner = ""
    i = 0
    while i < len(command):
        ch = command[i]
        if ch == "'":
            quoted = not quoted
        if not quoted and (ch in ";\n" or command.startswith("&&", i)):
            if "".join(cur).strip():
                out.append(("".join(cur).strip(), joiner))
            joiner = "&&" if ch == "&" else ";"
            cur = []
            i += 2 if ch == "&" else 1
            continue
        cur.append(ch)
        i += 1
    if "".join(cur).strip():
        out.append(("".join(cur).strip(), joiner))
    return out


def _set_type(match: Sequence[str]) -> str:
    return "ether_addr" if any("mac" in m for m in match) else "ipv4_addr"


def _set(items: Sequence[str]) -> str:
    quoted = [f'"{x}"' for x in items]
    return quoted[0] if len(quoted) == 1 else "{ " + ", ".join(quoted) + " }"


def _accepts_ssh(r: FwRuleConf, zone: ZoneConf, pc_ip: str) -> bool:
    return (
        r.enabled
        and r.src == zone.name
        and r.dest is None
        and r.target == "ACCEPT"
        and (r.proto is None or "tcp" in r.proto.split() or r.proto == "all")
        and (r.dest_port is None or str(SSH_PORT) in r.dest_port.split())
        and (not r.src_ip or pc_ip in r.src_ip)
    )


def _match(r: FwRuleConf) -> str:
    parts: list[str] = []
    if r.src_ip:
        parts.append(
            f"ip saddr {{ {', '.join(r.src_ip)} }}" if len(r.src_ip) > 1 else f"ip saddr {r.src_ip[0]}"
        )
    if r.dest_ip:
        parts.append(f"ip daddr {r.dest_ip[0]}")
    protos = (r.proto or "all").split()
    if r.icmp_type:
        parts.append(f"icmp type {r.icmp_type[0]}")
    elif protos != ["all"] and r.dest_port:
        port = r.dest_port.replace(" ", ", ")
        port = f"{{ {port} }}" if "," in port else port
        parts.append(
            f"{protos[0]} dport {port}"
            if len(protos) == 1
            else f"meta l4proto {{ {', '.join(protos)} }} th dport {port}"
        )
    elif protos != ["all"]:
        parts.append(f"meta l4proto {protos[0]}")
    return " ".join(parts)


_VERDICT = {"ACCEPT": "accept", "REJECT": "jump handle_reject", "DROP": "drop"}


def _rule_text(r: FwRuleConf, index: int) -> _Rule:
    name = r.name or f"@rule[{index}]"
    match = _match(r)
    return _Rule(
        f'{match + " " if match else ""}counter {_VERDICT.get(r.target, "accept")} comment "!fw4: {name}"'
    )


def _zone_chains(conf: FirewallConf, z: ZoneConf) -> list[_Chain]:
    numbered = list(enumerate(conf.rules))
    inp = [_rule_text(r, i) for i, r in numbered if r.enabled and r.src == z.name and r.dest is None]
    fwd = [_rule_text(r, i) for i, r in numbered if r.enabled and r.src == z.name and r.dest is not None]
    out = [_rule_text(r, i) for i, r in numbered if r.enabled and r.dest == z.name and r.src is None]
    fwd += [_Rule(f"jump accept_to_{f.dest}") for f in conf.forwardings if f.enabled and f.src == z.name]
    return [
        _Chain(f"input_{z.name}", None, [*inp, _Rule(f"jump {zone_tail('input', z.name, z.input)}")]),
        _Chain(f"forward_{z.name}", None, [*fwd, _Rule(f"jump {zone_tail('forward', z.name, z.forward)}")]),
        _Chain(f"output_{z.name}", None, [*out, _Rule(f"jump {zone_tail('output', z.name, z.output)}")]),
    ]


def _redirects(conf: FirewallConf) -> list[_Rule]:
    return [
        _Rule(
            f"meta nfproto ipv4 tcp dport {r.src_dport} counter dnat ip to {r.dest_ip}"
            + (f":{r.dest_port}" if r.dest_port else "")
            + f' comment "!fw4: {r.name}"'
        )
        for r in conf.redirects
        if r.enabled and r.name
    ]


def _nats(conf: FirewallConf) -> list[_Rule]:
    rules = [
        _Rule(
            (f"ip saddr {n.src_ip} " if n.src_ip else "")
            + (
                "counter masquerade"
                if n.target == "MASQUERADE"
                else "counter accept"
                if n.target == "ACCEPT"
                else f"counter snat ip to {n.snat_ip}"
            )
            + f' comment "!fw4: {n.name}"'
        )
        for n in conf.nats
        if n.enabled and n.name
    ]
    return rules


def _text(t: _Table, *, handles: bool) -> str:
    h = iter(range(1, 10_000))

    def tag() -> str:
        return f" # handle {next(h)}" if handles else ""

    lines = [f"table {t.family} {t.name} {{{tag()}"]
    for block in t.sets:
        first, *rest = block.split("\n")
        lines += [first + tag(), *rest]
    for c in t.chains:
        lines.append(f"\tchain {c.name} {{{tag()}")
        if c.decl:
            lines.append(f"\t\t{c.decl}")
        for r in c.rules:
            text = r.text.replace("counter", "counter packets 0 bytes 0", 1) if handles else r.text
            lines.append(f"\t\t{text}{tag()}")
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _json(tables: Sequence[_Table]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"metainfo": {"version": "1.1.1", "json_schema_version": 1}}]
    handle = 0
    for t in tables:
        handle += 1
        out.append({"table": {"family": t.family, "name": t.name, "handle": handle}})
        for block in t.sets:
            name = block.split()[1]
            handle += 1
            out.append({"set": {"family": t.family, "table": t.name, "name": name, "handle": handle}})
        for c in t.chains:
            handle += 1
            out.append(
                {"chain": {"family": t.family, "table": t.name, "name": c.name, "handle": handle, **c.hook()}}
            )
            for r in c.rules:
                handle += 1
                expr: list[dict[str, Any]] = []
                if "counter" in r.text.split():
                    expr.append({"counter": {"packets": 0, "bytes": 0}})
                expr.append({"jump": {"target": r.jump}} if r.jump else {"accept": None})
                rule: dict[str, Any] = {
                    "family": t.family,
                    "table": t.name,
                    "chain": c.name,
                    "handle": handle,
                    "expr": expr,
                }
                if r.comment is not None:
                    rule["comment"] = r.comment
                out.append({"rule": rule})
    return out
