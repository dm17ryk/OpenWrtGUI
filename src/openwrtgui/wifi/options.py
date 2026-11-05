"""All options for Wi-Fi: every option `network.wireless get_validate` accepts, through the shared forms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from openwrtgui import forms
from openwrtgui.forms import EditorKind, OptionEdit, OptionRow
from openwrtgui.uci import UciOp
from openwrtgui.wifi.writers import writer_of

__all__ = ["CONTROLLED", "READ_ONLY", "EditorKind", "OptionEdit", "OptionRow", "compile_edits", "editor_for"]

# Options with a hand-made control on the Wi-Fi screen link to it instead of being a second control.
CONTROLLED: dict[str, dict[str, str]] = {
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


def editor_for(name: str, type_: str) -> EditorKind:
    return forms.editor_for(name, type_, READ_ONLY)


def _writer(group: str, name: str) -> str | None:
    return writer_of(name) if group == "device" else None


def option_rows(
    radio: str,
    validate: Mapping[str, Mapping[str, str]],
    uci: Mapping[str, str],
    ssid_sections: Sequence[str],
) -> list[OptionRow]:
    targets = [("device", radio), *(("interface", s) for s in ssid_sections)]
    return forms.option_rows(
        "wireless", targets, validate, uci, controlled=CONTROLLED, read_only=READ_ONLY, writer_of=_writer
    )


def compile_edits(edits: Sequence[OptionEdit], rows: Sequence[OptionRow]) -> tuple[list[UciOp], list[str]]:
    return forms.compile_edits("wireless", edits, rows)
