"""Who owns each nft table and tc hook (spec 6, Ownership): fw4, this app, a known writer, or unknown."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.fw.nft import Ruleset
from openwrtgui.fw.tc import Qdisc
from openwrtgui.store.settings import KnownTable

Owner = Literal["fw4", "app", "known", "unknown"]
APP_TABLE = "benchfault"
APP_PREFIX = "owg_"
UNKNOWN = "Not created by fw4, this app or a known harness"
APP_ROOT = "1ee7:"
APP_IFB = "owgifb0"
KERNEL_DEFAULTS = frozenset({"noqueue", "fq_codel", "mq", "pfifo_fast"})


@dataclass(frozen=True)
class NftObject:
    key: str  # "bridge voipdscp", or "inet fw4 chain BENCHSIPGUARD"
    family: str
    table: str
    chain: str | None
    owner: Owner
    writer: str | None
    depends: str | None
    rules: int


@dataclass(frozen=True)
class TcHook:
    dev: str
    kind: str
    handle: str
    owner: Owner


def _known(key: str, known: Sequence[KnownTable]) -> KnownTable | None:
    return next((k for k in known if k.match == key), None)


def nft_objects(ruleset: Ruleset, known: Sequence[KnownTable]) -> list[NftObject]:
    """Every table (fw4's first) and every chain inside fw4's table that a known writer made."""
    out: list[NftObject] = []
    for family, table in ruleset.tables:
        rules = sum(1 for r in ruleset.rules if (r.family, r.table) == (family, table))
        key = f"{family} {table}"
        if (family, table) == ("inet", "fw4"):
            out.insert(0, NftObject(key, family, table, None, "fw4", None, None, rules))
            for chain in ruleset.chains:
                ck = f"{key} chain {chain.name}"
                if (chain.family, chain.table) == (family, table) and (writer := _known(ck, known)):
                    n = sum(
                        1
                        for r in ruleset.rules
                        if (r.family, r.table, r.chain) == (family, table, chain.name)
                    )
                    out.append(
                        NftObject(ck, family, table, chain.name, "known", writer.owner, writer.depends, n)
                    )
            continue
        if table == APP_TABLE or table.startswith(APP_PREFIX):
            out.append(NftObject(key, family, table, None, "app", "this app", None, rules))
        elif writer := _known(key, known):
            out.append(NftObject(key, family, table, None, "known", writer.owner, writer.depends, rules))
        else:
            out.append(NftObject(key, family, table, None, "unknown", None, UNKNOWN, rules))
    return out


def tc_hooks(qdiscs: Sequence[Qdisc], app_devices: frozenset[str]) -> list[TcHook]:
    """Every qdisc that is not the kernel's default; the app's own by handle, device or armed record."""
    out: list[TcHook] = []
    for q in qdiscs:
        if q.kind in KERNEL_DEFAULTS and q.handle == "0:":
            continue
        app = (
            q.dev == APP_IFB
            or (q.root and q.handle == APP_ROOT)
            or (q.parent or "").startswith(APP_ROOT)
            or (q.kind == "ingress" and q.dev in app_devices)
        )
        out.append(TcHook(q.dev, q.kind, q.handle, "app" if app else "unknown"))
    return out
