"""All options: every option the router's own list (network.wireless get_validate) accepts, as editors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.guard.audit import SECRET_OPTIONS
from openwrtgui.wifi.compile import UciOp
from openwrtgui.wifi.writers import writer_of

EditorKind = Literal["switch", "number", "text", "list", "secret", "readonly"]
Group = Literal["device", "interface"]

# Options with a hand-made control on the Wi-Fi screen link to it instead of being a second control.
CONTROLLED: dict[Group, dict[str, str]] = {
    "device": {
        "htmode": "Modes",
        "legacy_rates": "Modes",
        "supported_rates": "Modes",
        "basic_rate": "Modes",
        "noscan": "Modes",
        "channel": "Channels",
        "channels": "Channels",
        "disabled": "Channels (None = parked)",
        "txpower": "TX power",
        "country": "Country",
    },
    "interface": {
        "ssid": "SSID",
        "encryption": "Security",
        "key": "Security (hidden)",
        "macfilter": "Network & DHCP › Wi-Fi access by MAC",
        "maclist": "Network & DHCP › Wi-Fi access by MAC",
    },
}
READ_ONLY = frozenset({"type", "path", "phy", "device"})
SECRET_TYPES = frozenset({"<hidden>", "wpakey"})


@dataclass(frozen=True)
class OptionRow:
    group: Group
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
    value: str | list[str] | None = field(repr=False)  # None removes the option (driver default)


def editor_for(name: str, type_: str) -> EditorKind:
    if name in READ_ONLY:
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


def option_rows(
    radio: str,
    validate: Mapping[str, Mapping[str, str]],
    uci: Mapping[str, str],
    ssid_sections: Sequence[str],
) -> list[OptionRow]:
    targets: list[tuple[Group, str]] = [("device", radio), *(("interface", s) for s in ssid_sections)]
    rows: list[OptionRow] = []
    for group, section in targets:
        for name, type_ in validate.get(group, {}).items():
            path = f"wireless.{section}.{name}"
            editor = editor_for(name, type_)
            raw = uci.get(path)
            value: str | list[str] | None = raw
            if editor == "secret":
                value = None
            elif editor == "list" and raw is not None:
                value = raw.split()
            rows.append(
                OptionRow(
                    group=group,
                    section=section,
                    name=name,
                    type=type_,
                    editor=editor,
                    value=value,
                    set_in_config=raw is not None,
                    control=CONTROLLED[group].get(name),
                    writer=writer_of(name) if group == "device" else None,
                )
            )
    return rows


def compile_edits(edits: Sequence[OptionEdit], rows: Sequence[OptionRow]) -> tuple[list[UciOp], list[str]]:
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
        path = f"wireless.{edit.section}.{edit.name}"
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
