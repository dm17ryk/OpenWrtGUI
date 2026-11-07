"""uci changes for every config: one op per change, rendered as the exact shell lines the preview shows.

A new anonymous section is `<var>=$(uci add <config> <type>)` and later ops name it `<config>.$<var>`.
Section deletes run last, highest position first: deleting an anonymous section renumbers the
`cfgXXXXXX` names `uci -X show` gives the sections after it (plan v0.3: "Script shape").
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

OpKind = Literal["set", "delete", "add_list", "del_list", "add"]


@dataclass(frozen=True)
class UciOp:
    op: OpKind
    path: str
    value: str | None = None


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _new(path: str) -> bool:
    return "$" in path


def render_uci(ops: Sequence[UciOp], savedir: str | None = None) -> list[str]:
    uci = f"uci -P {savedir}" if savedir else "uci"
    lines = []
    for op in ops:
        if op.op == "delete":
            lines.append(f"{uci} -q delete {op.path}")
        elif op.op == "add":
            config, _, var = op.path.partition(".$")
            lines.append(f"{var}=$({uci} add {config} {op.value})")
        else:
            lines.append(f"{uci} {op.op} {op.path}={shell_quote(op.value or '')}")
    return lines


def _items(current: Mapping[str, str], path: str) -> list[str]:
    return current.get(path, "").split()


def drop_unchanged(ops: Sequence[UciOp], current: Mapping[str, str]) -> list[UciOp]:
    """Only changes are written: a set to the current value, a delete of an absent option or section and
    a del_list of an absent item go. An add_list stays: it usually follows a delete of the same list."""
    kept: list[UciOp] = []
    for op in ops:
        if op.op == "delete" and _new(op.path) and op.path.count(".") == 2:
            continue  # a section the script just made has no options: uci would exit 1 (AP2, 2026-11-07)
        if op.op == "add" or _new(op.path):
            kept.append(op)
        elif (
            op.op == "set"
            and current.get(op.path) == op.value
            or op.op == "delete"
            and op.path not in current
            or op.op == "del_list"
            and op.value not in _items(current, op.path)
        ):
            continue
        else:
            kept.append(op)
    return kept


def after(current: Mapping[str, str], ops: Sequence[UciOp]) -> dict[str, str]:
    """The config once `ops` ran. Sections the ops create (`$` paths) are not known until then."""
    out = dict(current)
    for op in ops:
        if op.op == "add" or _new(op.path):
            continue
        if op.op == "set":
            out[op.path] = op.value or ""
        elif op.op == "delete":
            out.pop(op.path, None)
            if op.path.count(".") == 1:  # a whole section
                out = {k: v for k, v in out.items() if not k.startswith(op.path + ".")}
        elif op.op == "add_list":
            out[op.path] = " ".join([*_items(out, op.path), op.value or ""])
        else:  # del_list
            items = [i for i in _items(out, op.path) if i != op.value]
            if items:
                out[op.path] = " ".join(items)
            else:
                out.pop(op.path, None)
    return out


def _section_delete(op: UciOp) -> bool:
    return op.op == "delete" and op.path.count(".") == 1 and not _new(op.path)


def order_for_script(ops: Sequence[UciOp], current: Mapping[str, str]) -> list[UciOp]:
    """Option changes first, in their order; then section deletes, the last section first."""
    sections = [k for k in current if k.count(".") == 1]
    rank = {name: i for i, name in enumerate(sections)}
    deletes = sorted((o for o in ops if _section_delete(o)), key=lambda o: rank.get(o.path, -1), reverse=True)
    return [o for o in ops if not _section_delete(o)] + deletes


def parse_uci_show(text: str) -> dict[str, str]:
    """`uci show` lines to {path: value}; a list's items are joined with spaces."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        path, sep, raw = line.partition("=")
        if not sep or not path:
            continue
        try:
            out[path] = " ".join(shlex.split(raw))
        except ValueError:
            out[path] = raw
    return out
