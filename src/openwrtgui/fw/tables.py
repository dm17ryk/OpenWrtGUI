"""Other nftables tables (spec 7.6, D12): one object per change, locked unless the request overrides,
written as nft's own text in one transaction (checked with `nft -c` first), rolled back by a router-side
timer, and kept at runtime or saved as an fw4 include."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.fw.nft import ChainText, TableText, render_table
from openwrtgui.fw.owners import APP_PREFIX, APP_TABLE, NftObject
from openwrtgui.net.apply import ROLLBACK_ID
from openwrtgui.uci import UciOp

FAMILIES = ("inet", "ip", "ip6", "bridge", "netdev", "arp")
INCLUDE_DIR = "/etc/owg/nft"
_TABLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,27}")
BACKUP = f"/tmp/owg/rb-{ROLLBACK_ID}.nft"


@dataclass(frozen=True)
class ChainEdit:
    name: str
    declaration: str | None


@dataclass(frozen=True)
class TableRequest:
    key: str  # NftObject.key; ignored for add
    action: Literal["edit", "add", "delete"]
    override: bool = False
    family: str | None = None
    name: str | None = None
    chains: tuple[ChainEdit, ...] = ()
    rules: tuple[tuple[str, str], ...] = ()  # (chain, body) in order
    keep: Literal["runtime", "include"] = "runtime"


@dataclass(frozen=True)
class TableChange:
    key: str
    script: str  # the nft transaction
    backup: tuple[str, ...]
    restore: tuple[str, ...]
    listing: str  # lists the object afterwards (verify) and before (the rollback's snapshot)
    expect: TableText | ChainText | None  # what the listing must show; None: the object is gone
    include_ops: tuple[UciOp, ...]
    include_commands: tuple[str, ...]
    include_file: tuple[str, str] | None  # (path, content) the include must hold
    warnings: tuple[str, ...]


def heredoc(head: str, text: str) -> str:
    """A command whose stdin is `text`, shown and sent whole (no stdin channel)."""
    if "OWG" in text.splitlines():
        raise ValueError("The text may not contain a line that reads OWG")
    return f"{head} <<'OWG'\n{text}\nOWG"


def owner_text(obj: NftObject) -> str:
    return obj.writer or "an unknown writer"


def refuse_locked(req: TableRequest, obj: NftObject) -> None:
    if obj.owner == "fw4":
        raise ValueError(f"{obj.key} is fw4's own table: change it on the other tabs.")
    if obj.table == APP_TABLE:  # an edit here would leave the fault records and timers on chains that changed
        raise ValueError(f"{obj.key} holds the faults this app armed: clear them on the Faults screen.")
    if obj.owner != "app" and not req.override:
        raise ValueError(f"{obj.key} belongs to {owner_text(obj)}; unlock it first.")


def _chains(req: TableRequest, current: Sequence[ChainText], key: str) -> tuple[ChainText, ...]:
    shapes = [(c.name, c.declaration) for c in req.chains] or [(c.name, c.declaration) for c in current]
    names = [name for name, _ in shapes]
    for chain, _ in req.rules:
        if chain not in names:
            raise ValueError(f"There is no chain {chain} in {key}")
    return tuple(
        ChainText(name, decl, tuple(body.strip() for c, body in req.rules if c == name))
        for name, decl in shapes
    )


def _include(
    section: str, path: str, position: str, content: str
) -> tuple[tuple[UciOp, ...], tuple[str, ...], tuple[str, str]]:
    p = f"firewall.{section}"
    ops = (
        UciOp("set", p, "include"),
        UciOp("set", f"{p}.type", "nftables"),
        UciOp("set", f"{p}.path", path),
        UciOp("set", f"{p}.position", position),
    )
    return ops, (f"mkdir -p {INCLUDE_DIR}", heredoc(f"cat > {path}", content)), (path, content)


def table_change(
    req: TableRequest, obj: NftObject | None, current: TableText | None, included: frozenset[str]
) -> TableChange:
    """`included`: the uci include sections the app saved before (owg_<family>_<table>…)."""
    if req.action == "add":
        return _add(req)
    if obj is None:
        raise ValueError(f"There is no table {req.key}")
    refuse_locked(req, obj)
    warnings: tuple[str, ...] = (
        (f"{obj.key} belongs to {owner_text(obj)}: the change is written to the audit log as an override.",)
        if obj.owner != "app"
        else ()
    )
    if obj.chain is not None:
        return _fw4_chain(req, obj, current, included, warnings)
    if current is None:
        raise ValueError(f"There is no table {req.key}")
    f, n = obj.family, obj.table
    section, path = f"owg_{f}_{n}", f"{INCLUDE_DIR}/{f}-{n}.nft"
    listing = f"nft list table {f} {n}"
    backup = (f"{listing} > {BACKUP}",)
    restore = (f"nft delete table {f} {n} 2>/dev/null", f"nft -f {BACKUP}")
    if req.action == "delete":
        saved = section in included
        return TableChange(
            obj.key,
            f"delete table {f} {n}",
            backup,
            restore,
            listing,
            None,
            (UciOp("delete", f"firewall.{section}"),) if saved else (),
            (f"rm -f {path}",) if saved else (),
            None,
            warnings,
        )
    new = TableText(f, n, current.sets, _chains(req, current.chains, obj.key))
    text = render_table(new).rstrip("\n")
    ops: tuple[UciOp, ...] = ()
    commands: tuple[str, ...] = ()
    file: tuple[str, str] | None = None
    if req.keep == "include":
        ops, commands, file = _include(
            section, path, "ruleset-post", f"add table {f} {n}\nflush table {f} {n}\n{text}"
        )
    elif section in included:
        warnings += (f"A saved fw4 include for {obj.key} loads its old rules at the next restart.",)
    return TableChange(
        obj.key, f"delete table {f} {n}\n{text}", backup, restore, listing, new, ops, commands, file, warnings
    )


def _fw4_chain(
    req: TableRequest,
    obj: NftObject,
    current: TableText | None,
    included: frozenset[str],
    warnings: tuple[str, ...],
) -> TableChange:
    chain = obj.chain
    assert chain is not None
    if req.action == "delete":
        raise ValueError("Only whole tables are deleted here")
    for name, _ in req.rules:
        if name != chain:
            raise ValueError(f"There is no chain {name} in {obj.key}")
    bodies = tuple(body.strip() for _, body in req.rules)
    script = "\n".join([f"flush chain inet fw4 {chain}", *(f"add rule inet fw4 {chain} {b}" for b in bodies)])
    listing = f"nft list chain inet fw4 {chain}"
    section, path = f"owg_inet_fw4_{chain}", f"{INCLUDE_DIR}/inet-fw4-{chain}.nft"
    ops: tuple[UciOp, ...] = ()
    commands: tuple[str, ...] = ()
    file: tuple[str, str] | None = None
    if req.keep == "include":
        content = "\n".join([f"chain {chain} {{", *(f"\t{b}" for b in bodies), "}"])
        ops, commands, file = _include(section, path, "table-post", content)
    elif section in included:
        warnings += (f"A saved fw4 include for {obj.key} loads its old rules at the next restart.",)
    return TableChange(
        obj.key,
        script,
        (f"{listing} > {BACKUP}",),
        (f"nft flush chain inet fw4 {chain}", f"nft -f {BACKUP}"),
        listing,
        ChainText(chain, None, bodies),
        ops,
        commands,
        file,
        warnings,
    )


def _add(req: TableRequest) -> TableChange:
    family = req.family or ""
    if family not in FAMILIES:
        raise ValueError(f"{family or 'The family'} is not one of {', '.join(FAMILIES)}")
    if not _TABLE_NAME.fullmatch(req.name or ""):
        raise ValueError("A table name is letters, digits or _ (it is saved as owg_<name>)")
    name = f"{APP_PREFIX}{req.name}"
    key = f"{family} {name}"
    new = TableText(family, name, (), _chains(req, (), key))
    text = render_table(new).rstrip("\n")
    ops: tuple[UciOp, ...] = ()
    commands: tuple[str, ...] = ()
    file: tuple[str, str] | None = None
    if req.keep == "include":
        path = f"{INCLUDE_DIR}/{family}-{name}.nft"
        content = f"add table {family} {name}\nflush table {family} {name}\n{text}"
        ops, commands, file = _include(f"owg_{family}_{name}", path, "ruleset-post", content)
    return TableChange(
        key, text, (), (f"nft delete table {family} {name}",), "nft list tables", new, ops, commands, file, ()
    )
