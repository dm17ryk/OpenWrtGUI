"""LuCI's Status › Firewall (iptables) view (v1.0a2 D6): the legacy rules per table, as LuCI lists and parses
them (luci-mod-status view/status/iptables.js)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Program = Literal["iptables", "ip6tables"]
TABLES = ("filter", "nat", "mangle", "raw")
PROGRAMS: dict[Program, str] = {"iptables": "/usr/sbin/iptables", "ip6tables": "/usr/sbin/ip6tables"}
ZERO: dict[Program, str] = {"iptables": "iptables -Z", "ip6tables": "ip6tables -Z"}
RESTART = "/etc/init.d/firewall restart"
RESET_NOTE = "Resets the filter table's counters only, as LuCI does: nat, mangle and raw keep theirs."
_POLICY = re.compile(r"Chain (.+) \(policy (\w+) (\d+) packets, (\d+) bytes\)")
_REFS = re.compile(r"Chain (.+) \((\d+) references\)")
_ADDR = r"!?[a-f0-9:.]+(?:/[a-f0-9:.]+)?"
# LuCI's rule pattern; the options column is optional here (a rule line may end at its destination)
_RULE = re.compile(
    rf"(\d+) +(\d+) +(\d+) +(.*?) +(\S+) +(\S*) +(\S+) +(\S+) +({_ADDR}) +({_ADDR})(?: +(.*))?"
)
_COMMENT = re.compile(r"/\* (.*?) \*/")


class IptRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    num: int
    packets: int
    bytes: int
    target: str
    prot: str
    opt: str
    inp: str
    out: str
    source: str
    destination: str
    options: str
    comment: str | None


class IptChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    policy: str | None  # built-in chains; user chains have references instead
    packets: int | None
    bytes: int | None
    references: int | None
    rules: list[IptRule]


class IptTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    program: Program
    table: str
    chains: list[IptChain]
    error: str | None = None


class IptablesPresence(BaseModel):
    model_config = ConfigDict(frozen=True)

    iptables: bool
    ip6tables: bool


class IptablesState(BaseModel):
    model_config = ConfigDict(frozen=True)

    iptables: bool
    ip6tables: bool
    tables: list[IptTable]


def listing(program: Program, table: str) -> str:
    if program not in PROGRAMS or table not in TABLES:
        raise ValueError(f"LuCI lists {', '.join(TABLES)} with iptables or ip6tables, not {program} {table}")
    return f"{program} --line-numbers -w -nvxL -t {table}"


def _rule(m: re.Match[str]) -> IptRule:
    options = (m.group(11) or "").strip()
    comment = _COMMENT.search(options)
    return IptRule(
        num=int(m.group(1)),
        packets=int(m.group(2)),
        bytes=int(m.group(3)),
        target=m.group(4),
        prot=m.group(5),
        opt=m.group(6),
        inp=m.group(7),
        out=m.group(8),
        source=m.group(9),
        destination=m.group(10),
        options=_COMMENT.sub("", options).strip(),
        comment=comment.group(1).removeprefix("!fw3: ") if comment else None,
    )


def parse_listing(text: str) -> list[IptChain]:
    heads: list[IptChain] = []
    rules: list[list[IptRule]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if m := _POLICY.fullmatch(stripped):
            policy, packets, counted = m[2], int(m[3]), int(m[4])
            heads.append(
                IptChain(name=m[1], policy=policy, packets=packets, bytes=counted, references=None, rules=[])
            )
            rules.append([])
        elif m := _REFS.fullmatch(stripped):
            heads.append(
                IptChain(name=m[1], policy=None, packets=None, bytes=None, references=int(m[2]), rules=[])
            )
            rules.append([])
        elif heads and (m := _RULE.fullmatch(line.rstrip())):
            rules[-1].append(_rule(m))
    return [h.model_copy(update={"rules": r}) for h, r in zip(heads, rules, strict=True)]
