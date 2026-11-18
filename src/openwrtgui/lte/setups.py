"""Saved good setups (spec 4.4): a router's working LTE options, kept as <data>/lte-setups/<router_id>.json.

The file holds the APN password and SIM PIN as the router has them, so the folder is the current Windows
user's only, the secrets stay out of `repr`, and the summaries the API lists never carry them."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openwrtgui.forms import OptionEdit, OptionRow
from openwrtgui.lte.at import ModemInfo
from openwrtgui.lte.settings import LteSettings
from openwrtgui.store import keys, write_atomic

ROUTER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# The Settings card's own fields (LteSettings), as uci options. Their rows may name the field as their control
# (mtu: "MTU"); they are still saved. Other controlled rows (device, dhcp, autoconnect) are not.
NAMED = ("apn", "auth", "username", "password", "pincode", "pdptype", "mtu", "metric", "auto", "defaultroute")


class SetupUnreadable(ValueError):
    """A setup file that is cut off or edited into something else (422, naming the file)."""


class LteSetup(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    router_name: str
    saved_at: datetime
    modem: ModemInfo
    options: dict[str, str] = Field(repr=False)  # raw values, password and pincode included


class LteSetupSummary(BaseModel):
    """What the setup list shows: never an option value but the APN and PDP type."""

    model_config = ConfigDict(frozen=True)

    router_id: str
    router_name: str
    saved_at: datetime | None
    apn: str | None
    pdptype: str | None
    readable: bool


@dataclass(frozen=True)
class SetupChange:
    """Reconfigure's settings change, the saved options the target has no row for (not written), and the
    options left as they are because the Settings card cannot remove them (the MTU)."""

    settings: LteSettings
    skipped: tuple[str, ...]
    kept: tuple[str, ...]


_TEXT_FIELDS = ("apn", "auth", "username", "password", "pincode", "pdptype")
_ROWLESS = ("auto",)  # the interface's own field: no row in All options
_DEFAULT_ON = ("auto", "defaultroute")  # missing means on


def _same(name: str, saved: str | None, current: str | None) -> bool:
    if name in _DEFAULT_ON:
        return (saved or "1") == (current or "1")
    return saved == current


def _number(name: str, value: str) -> int:
    if not value.isdigit():
        raise ValueError(f"The setup's {name} {value!r} is not a whole number")
    return int(value)


def setup_change(
    setup: LteSetup,
    rows: Sequence[OptionRow],
    values: Mapping[str, str],
    *,
    same_router: bool,
    section: str = "lte",
) -> SetupChange:
    """Spec 4.4: set every saved option whose value differs, remove every option the router has that the setup
    lacks, never the device, and from another router's setup never the PIN. Only options the Settings card
    edits are touched: its named fields and the rows without a control of their own."""
    by_name = {row.name: row for row in rows}
    editable = {n for n, row in by_name.items() if row.control is None and row.editor != "readonly"}
    candidates = (editable | set(NAMED)) - {"device"} - (set() if same_router else {"pincode"})
    saved = {k: v for k, v in setup.options.items() if k in candidates or k not in by_name}
    skipped = tuple(sorted(n for n in saved if n not in by_name and n not in _ROWLESS))
    wanted = {k: v for k, v in saved.items() if k in candidates and (k in by_name or k in _ROWLESS)}
    removed = sorted(n for n in values if n in candidates and n not in wanted)
    fields: dict[str, object] = {}
    edits: list[OptionEdit] = []
    kept: list[str] = []
    for name in sorted(wanted):
        if _same(name, wanted[name], values.get(name)):
            continue
        value = wanted[name]
        if name in _TEXT_FIELDS:
            fields[name] = value
        elif name in ("mtu", "metric"):
            fields[name] = _number(name, value)
        elif name in _DEFAULT_ON:
            fields[name] = value != "0"
        else:
            edits.append(OptionEdit(section, name, value))
    for name in removed:
        if _same(name, None, values.get(name)):
            continue
        if name in _TEXT_FIELDS:
            fields[name] = ""
        elif name == "auto":
            fields[name] = True  # netifd's default: bring up at boot
        elif name == "mtu":
            kept.append(name)
        else:
            edits.append(OptionEdit(section, name, None))
    return SetupChange(
        settings=LteSettings(**fields, edits=tuple(edits)),  # type: ignore[arg-type]
        skipped=skipped,
        kept=tuple(kept),
    )


def summary_of(setup: LteSetup) -> LteSetupSummary:
    return LteSetupSummary(
        router_id=setup.router_id,
        router_name=setup.router_name,
        saved_at=setup.saved_at,
        apn=setup.options.get("apn"),
        pdptype=setup.options.get("pdptype"),
        readable=True,
    )


class SetupStore:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def _path(self, router_id: str) -> Path:
        if not ROUTER_ID.fullmatch(router_id):
            raise ValueError(f"{router_id!r} is not a router id")
        return self._folder / f"{router_id}.json"

    @staticmethod
    def _load(path: Path) -> LteSetup:
        try:
            return LteSetup.model_validate_json(path.read_bytes())
        except (ValidationError, UnicodeDecodeError) as exc:
            raise SetupUnreadable(f"{path.name} cannot be read") from exc

    def get(self, router_id: str) -> LteSetup | None:
        path = self._path(router_id)
        return self._load(path) if path.is_file() else None

    def save(self, setup: LteSetup) -> None:
        """Blocking (icacls on Windows): call it off the event loop."""
        path = self._path(setup.router_id)
        self._folder.mkdir(parents=True, exist_ok=True)
        keys.restrict_to_user(self._folder)  # before the first secret lands; new files inherit it
        write_atomic(path, setup.model_dump_json(indent=2))

    def delete(self, router_id: str) -> None:
        self._path(router_id).unlink(missing_ok=True)

    def summaries(self) -> list[LteSetupSummary]:
        if not self._folder.is_dir():
            return []
        out: list[LteSetupSummary] = []
        for path in sorted(self._folder.glob("*.json")):
            try:
                out.append(summary_of(self._load(path)))
            except SetupUnreadable:
                stem = path.stem
                out.append(
                    LteSetupSummary(
                        router_id=stem,
                        router_name=stem,
                        saved_at=None,
                        apn=None,
                        pdptype=None,
                        readable=False,
                    )
                )
        return out
