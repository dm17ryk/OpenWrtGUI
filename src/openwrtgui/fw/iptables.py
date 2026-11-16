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
_HEADER = re.compile(r"num\s+pkts\s+bytes\s+target\b.*")


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
    skipped: int = 0  # lines of the listing the parser could not read (v1.0b2 D4)


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


MARK = "### owg-ipt"  # the section lines of IPT_STATE's answer
_SEEN = ("present", "absent")


def _state_command() -> str:
    """Every program's presence and every table's listing in one command (v1.0c Task 3, #63): LuCI's own
    listings, each between markers with its exit status, errors folded into the section."""
    parts: list[str] = []
    for program, path in PROGRAMS.items():
        parts.append(
            f'if [ -x {path} ]; then echo "{MARK} {program} present"; else echo "{MARK} {program} absent"; fi'
        )
        for table in TABLES:
            head = f'echo "{MARK} {program} {table}"'
            parts.append(f'{head}; {listing(program, table)} 2>&1; echo "{MARK} exit $?"')
    return "; ".join(parts)


IPT_STATE = _state_command()


def _program(word: str) -> Program | None:
    return "iptables" if word == "iptables" else "ip6tables" if word == "ip6tables" else None


def split_state(text: str) -> tuple[IptablesPresence, dict[tuple[Program, str], tuple[int, str]]]:
    """IPT_STATE's answer: presence per program, and (exit status, listing) per table it finished. A table cut
    off before its exit line is left out, so it shows as unanswered rather than as a short listing."""
    present: dict[Program, bool] = {"iptables": False, "ip6tables": False}
    tables: dict[tuple[Program, str], tuple[int, str]] = {}
    current: tuple[Program, str] | None = None
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        words = line.removeprefix(f"{MARK} ").split() if line.startswith(f"{MARK} ") else []
        if len(words) == 2 and words[0] == "exit" and current is not None:
            tables[current] = (int(words[1]) if words[1].isdigit() else 1, "".join(lines))
            current = None
        elif len(words) == 2 and (program := _program(words[0])) is not None and words[1] in TABLES:
            current, lines = (program, words[1]), []
        elif len(words) == 2 and (program := _program(words[0])) is not None and words[1] in _SEEN:
            present[program] = words[1] == "present"
        elif current is not None:
            lines.append(line)
    return IptablesPresence(iptables=present["iptables"], ip6tables=present["ip6tables"]), tables


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


def skipped_lines(text: str) -> int:
    """Lines `parse_listing` shows nothing for: not a chain head, the column header, a rule or blank. A `#`
    line is iptables' own note (iptables-nft's warning, folded in from stderr), not a rule (final review)."""
    return sum(
        1
        for line in text.splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and not _POLICY.fullmatch(line.strip())
        and not _REFS.fullmatch(line.strip())
        and not _HEADER.fullmatch(line.strip())
        and not _RULE.fullmatch(line.rstrip())
    )


def _counters(text: str) -> dict[tuple[str, int], int]:
    """Every byte counter in a listing: (chain, 0) for a built-in chain's policy, (chain, n) for rule n."""
    out: dict[tuple[str, int], int] = {}
    for chain in parse_listing(text):
        if chain.bytes is not None:
            out[(chain.name, 0)] = chain.bytes
        out |= {(chain.name, r.num): r.bytes for r in chain.rules}
    return out


def reset_proven(before: str, after: str) -> bool:
    """Counters only grow between resets: one that counted before and is lower now proves the reset, also
    after an earlier reset with traffic since (v1.0b2 D4). Nothing counted before: nothing to prove."""
    was, now = _counters(before), _counters(after)
    counted = {key: n for key, n in was.items() if n > 0}
    # a counter missing afterwards (the listing lost the rule, or failed) proves nothing (v1.0c Task 10)
    return not counted or any(key in now and now[key] < n for key, n in counted.items())
