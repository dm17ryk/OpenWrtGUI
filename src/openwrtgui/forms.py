"""All options: every option a router's typed list accepts, as editors (spec 5, "Forms from typed options").

The lists come from the router: `network.wireless get_validate` for Wi-Fi, `network get_proto_handlers`
for interfaces. Options with a hand-made control on the screen link to it instead of being a second control.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.guard.audit import SECRET_OPTIONS
from openwrtgui.uci import UciOp

EditorKind = Literal["switch", "number", "text", "list", "secret", "readonly"]
SECRET_TYPES = frozenset({"<hidden>", "wpakey"})


@dataclass(frozen=True)
class OptionRow:
    config: str
    group: str
    section: str
    name: str
    type: str
    editor: EditorKind
    value: str | list[str] | None = field(repr=False)
    set_in_config: bool
    control: str | None
    writer: str | None


@dataclass(frozen=True)
class OptionEdit:
    section: str
    name: str
    value: str | list[str] | None = field(repr=False)  # None removes the option (the default applies)


def editor_for(name: str, type_: str, read_only: frozenset[str] = frozenset()) -> EditorKind:
    if name in read_only:
        return "readonly"
    if name in SECRET_OPTIONS or type_ in SECRET_TYPES:
        return "secret"
    if type_ == "bool":
        return "switch"
    if type_ in ("uinteger", "integer"):
        return "number"
    if type_.startswith("list("):
        return "list"
    return "text"


def _no_writer(group: str, name: str) -> str | None:
    return None


def option_rows(
    config: str,
    targets: Sequence[tuple[str, str]],
    validate: Mapping[str, Mapping[str, str]],
    uci: Mapping[str, str],
    *,
    controlled: Mapping[str, Mapping[str, str]] | None = None,
    read_only: frozenset[str] = frozenset(),
    writer_of: Callable[[str, str], str | None] = _no_writer,
) -> list[OptionRow]:
    """One row per option of each (group, section) target, in the router's own order."""
    rows: list[OptionRow] = []
    for group, section in targets:
        for name, type_ in validate.get(group, {}).items():
            raw = uci.get(f"{config}.{section}.{name}")
            editor = editor_for(name, type_, read_only)
            value: str | list[str] | None = raw
            if editor == "secret":
                value = None
            elif editor == "list" and raw is not None:
                value = raw.split()
            rows.append(
                OptionRow(
                    config=config,
                    group=group,
                    section=section,
                    name=name,
                    type=type_,
                    editor=editor,
                    value=value,
                    set_in_config=raw is not None,
                    control=(controlled or {}).get(group, {}).get(name),
                    writer=writer_of(group, name),
                )
            )
    return rows


def compile_edits(
    config: str, edits: Sequence[OptionEdit], rows: Sequence[OptionRow]
) -> tuple[list[UciOp], list[str]]:
    """uci operations for the edits, and the secret values among them (hidden in the preview)."""
    by_key = {(r.section, r.name): r for r in rows}
    ops: list[UciOp] = []
    secrets: list[str] = []
    for edit in edits:
        row = by_key.get((edit.section, edit.name))
        if row is None:
            raise ValueError(f"{edit.name} is not an option of {edit.section}")
        if row.editor == "readonly":
            raise ValueError(f"{edit.name} is read-only")
        if row.control:  # its control runs checks a plain row would skip (#26)
            raise ValueError(f"{edit.name} has its own control ({row.control}); change it there.")
        path = f"{config}.{edit.section}.{edit.name}"
        if edit.value is None:
            ops.append(UciOp("delete", path))
            continue
        if row.editor == "list":
            items = edit.value if isinstance(edit.value, list) else str(edit.value).split()
            ops += [UciOp("delete", path), *(UciOp("add_list", path, item) for item in items)]
            continue
        value = " ".join(edit.value) if isinstance(edit.value, list) else edit.value
        if row.editor == "number" and not (
            value.isdigit() or (row.type == "integer" and value.lstrip("-").isdigit())
        ):
            raise ValueError(f"{edit.name} takes a whole number")
        if row.editor == "switch" and value not in ("0", "1"):
            raise ValueError(f"{edit.name} is on or off")
        if row.editor == "secret":
            secrets.append(value)
        ops.append(UciOp("set", path, value))
    return ops, secrets
