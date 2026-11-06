"""nftables output: `nft -j list ruleset` for structure, hooks and counters; `nft -a list ruleset` for rule
text by handle and for whole tables as text (an edit writes a table back as nft's own syntax)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openwrtgui.fw.model import Direction, Policy

_HANDLE = re.compile(r"\s+# handle (\d+)$")
_COUNTER = re.compile(r"counter packets \d+ bytes \d+")
_TABLE = re.compile(r"^table (\S+) (\S+) \{$")
_CHAIN = re.compile(r"^chain (\S+) \{$")


@dataclass(frozen=True)
class NftChain:
    family: str
    table: str
    name: str
    type: str | None
    hook: str | None
    priority: int | None
    policy: str | None
    device: str | None


@dataclass(frozen=True)
class NftRule:
    family: str
    table: str
    chain: str
    handle: int
    comment: str | None
    packets: int | None
    bytes: int | None
    jump: str | None  # the target of a trailing jump or goto


@dataclass(frozen=True)
class NftSet:
    family: str
    table: str
    name: str


@dataclass(frozen=True)
class Ruleset:
    tables: tuple[tuple[str, str], ...]
    chains: tuple[NftChain, ...]
    rules: tuple[NftRule, ...]
    sets: tuple[NftSet, ...]


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _rule(raw: dict[str, Any]) -> NftRule | None:
    if not all(isinstance(raw.get(k), str) for k in ("family", "table", "chain")):
        return None
    handle = _int(raw.get("handle"))
    if handle is None:
        return None
    exprs = [e for e in raw.get("expr", []) if isinstance(e, dict)]
    counter: dict[str, Any] = next((e["counter"] for e in exprs if isinstance(e.get("counter"), dict)), {})
    last = exprs[-1] if exprs else {}
    target = (last.get("jump") or last.get("goto") or {}) if isinstance(last, dict) else {}
    return NftRule(
        family=raw["family"],
        table=raw["table"],
        chain=raw["chain"],
        handle=handle,
        comment=raw.get("comment") if isinstance(raw.get("comment"), str) else None,
        packets=_int(counter.get("packets")),
        bytes=_int(counter.get("bytes")),
        jump=target.get("target") if isinstance(target, dict) else None,
    )


def parse_ruleset_json(text: str) -> Ruleset:
    try:
        items = json.loads(text).get("nftables", [])
    except (ValueError, AttributeError):
        items = []
    tables: list[tuple[str, str]] = []
    chains: list[NftChain] = []
    rules: list[NftRule] = []
    sets: list[NftSet] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(t := item.get("table"), dict) and isinstance(t.get("name"), str):
            tables.append((str(t.get("family")), t["name"]))
        elif isinstance(c := item.get("chain"), dict) and isinstance(c.get("name"), str):
            chains.append(
                NftChain(
                    family=str(c.get("family")),
                    table=str(c.get("table")),
                    name=c["name"],
                    type=c.get("type"),
                    hook=c.get("hook"),
                    priority=_int(c.get("prio")),
                    policy=c.get("policy"),
                    device=c.get("dev") if isinstance(c.get("dev"), str) else None,
                )
            )
        elif isinstance(r := item.get("rule"), dict):
            if (rule := _rule(r)) is not None:
                rules.append(rule)
        elif isinstance(s := item.get("set"), dict) and isinstance(s.get("name"), str):
            sets.append(NftSet(str(s.get("family")), str(s.get("table")), s["name"]))
    return Ruleset(tuple(tables), tuple(chains), tuple(rules), tuple(sets))


def _clean(line: str) -> str:
    """A listed rule as it can be written back: no handle comment, counters without their values."""
    return _COUNTER.sub("counter", _HANDLE.sub("", line.strip()))


def _depth(line: str) -> int:
    return len(line) - len(line.lstrip("\t"))


def rule_texts(text: str) -> dict[tuple[str, str, int], str]:
    """`nft -a list ruleset` → (family, table, handle) → the rule's text."""
    out: dict[tuple[str, str, int], str] = {}
    table: tuple[str, str] | None = None
    in_chain = False
    for line in text.splitlines():
        depth, body = _depth(line), _HANDLE.sub("", line.strip())
        if depth == 0 and (m := _TABLE.match(body)):
            table = (m.group(1), m.group(2))
        elif depth == 1:
            in_chain = bool(_CHAIN.match(body))
        elif depth == 2 and in_chain and table and (h := _HANDLE.search(line)):
            out[(table[0], table[1], int(h.group(1)))] = _clean(line)
    return out


@dataclass(frozen=True)
class ChainText:
    name: str
    declaration: str | None
    rules: tuple[str, ...]


@dataclass(frozen=True)
class TableText:
    family: str
    name: str
    sets: tuple[str, ...]  # named sets, maps, flowtables… as listed (tab-indented blocks)
    chains: tuple[ChainText, ...]


def table_texts(text: str) -> dict[tuple[str, str], TableText]:
    """`nft list ruleset` (with or without -a) → every table as text nft takes back."""
    out: dict[tuple[str, str], TableText] = {}
    table: tuple[str, str] | None = None
    sets: list[str] = []
    chains: list[ChainText] = []
    block: list[str] | None = None  # a set or other named object being read
    chain: tuple[str, str | None, list[str]] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        depth, body = _depth(line), _HANDLE.sub("", line.strip())
        if depth == 0:
            if m := _TABLE.match(body):
                table, sets, chains = (m.group(1), m.group(2)), [], []
            elif body == "}" and table:
                out[table] = TableText(table[0], table[1], tuple(sets), tuple(chains))
                table = None
        elif depth == 1:
            if body == "}":
                if chain is not None:
                    chains.append(ChainText(chain[0], chain[1], tuple(chain[2])))
                    chain = None
                elif block is not None:
                    sets.append("\n".join([*block, "\t}"]))
                    block = None
            elif m := _CHAIN.match(body):
                chain = (m.group(1), None, [])
            else:
                block = ["\t" + body]
        elif chain is not None:
            if body.startswith("type ") and chain[1] is None and not chain[2]:
                chain = (chain[0], body, chain[2])
            else:
                chain[2].append(_clean(line))
        elif block is not None:
            block.append("\t" * depth + body)
    return out


def render_table(t: TableText) -> str:
    lines = [f"table {t.family} {t.name} {{", *t.sets]
    for c in t.chains:
        lines.append(f"\tchain {c.name} {{")
        if c.declaration:
            lines.append(f"\t\t{c.declaration}")
        lines += [f"\t\t{rule}" for rule in c.rules]
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def zone_tail(direction: Direction, zone: str, policy: Policy) -> str:
    """The chain fw4 jumps to at the end of `<direction>_<zone>`: the zone's policy in effect."""
    return f"{policy.lower()}_{'from' if direction == 'input' else 'to'}_{zone}"


def rules_with_comment(ruleset: Ruleset, comment: str) -> Sequence[NftRule]:
    return [r for r in ruleset.rules if r.comment == comment]
