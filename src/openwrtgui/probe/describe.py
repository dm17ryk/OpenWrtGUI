"""Read what a router says about itself, from the same sources LuCI uses (D18)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from openwrtgui.probe import commands as c
from openwrtgui.probe.board import BoardInfo, parse_board_json
from openwrtgui.probe.identity import Identity, build_identity, parse_release
from openwrtgui.probe.ubus_list import parse_ubus_list
from openwrtgui.transport.base import Transport, ubus_call

_BLOCK = re.compile(r"^=== (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class LuciInfo:
    packages: tuple[str, ...]
    menu_entries: int
    acl_groups: tuple[str, ...]


@dataclass(frozen=True)
class SelfDescription:
    identity: Identity
    board: BoardInfo | None
    services: dict[str, dict[str, dict[str, str]]]
    features: dict[str, Any] | None
    protocols: dict[str, dict[str, str]]
    wireless_options: dict[str, dict[str, dict[str, str]]]
    luci: LuciInfo | None
    root_password: Literal["none", "set", "unknown"]
    read_at: datetime


@dataclass(frozen=True)
class DescriptionSummary:
    model: str
    hostname: str
    revision: str
    target: str
    services: int
    protocols: dict[str, int]
    wireless_options: dict[str, dict[str, int]]
    features_on: dict[str, bool]
    luci_packages: int
    luci_menu_entries: int
    port_labels: dict[int, str]


def _json_blocks(text: str) -> dict[str, dict[str, Any]]:
    """Split the `=== path` + JSON output of the menu/ACL loops into {file stem: object}."""
    parts = _BLOCK.split(text)
    out: dict[str, dict[str, Any]] = {}
    for path, body in zip(parts[1::2], parts[2::2], strict=False):
        try:
            data = json.loads(body)
        except ValueError:
            continue
        if isinstance(data, dict):
            out[PurePosixPath(path.strip()).stem] = data
    return out


async def _stdout(t: Transport, command: str) -> str | None:
    r = await t.run(command)
    return r.stdout if r.ok else None


async def describe_router(t: Transport) -> SelfDescription:
    release = parse_release(await _stdout(t, c.RELEASE) or "")
    identity = build_identity(release, await ubus_call(t, "system", "board") or {})

    board_text = await _stdout(t, c.BOARD_JSON)
    board: BoardInfo | None = None
    if board_text:
        try:
            board = parse_board_json(board_text)
        except (ValueError, KeyError):
            board = None

    services = parse_ubus_list(await _stdout(t, c.UBUS_LIST) or "")
    features = await ubus_call(t, "luci", "getFeatures")
    handlers = await ubus_call(t, "network", "get_proto_handlers") or {}
    protocols = {name: dict(h.get("validate", {})) for name, h in handlers.items() if isinstance(h, dict)}

    status = await ubus_call(t, "network.wireless", "status") or {}
    radios = list(status) or [f"radio{i}" for i, _ in enumerate(board.radios if board else ())]
    wireless_options: dict[str, dict[str, dict[str, str]]] = {}
    for radio in radios:
        validate = await ubus_call(t, "network.wireless", "get_validate", {"device": radio}) or {}
        groups = validate.get(radio)
        if isinstance(groups, dict):
            wireless_options[radio] = {g: dict(v) for g, v in groups.items() if isinstance(v, dict)}

    menus = _json_blocks(await _stdout(t, c.LUCI_MENU) or "")
    acls = _json_blocks(await _stdout(t, c.LUCI_ACL) or "")
    luci = (
        LuciInfo(
            packages=tuple(sorted(menus)),
            menu_entries=sum(len(m) for m in menus.values()),
            acl_groups=tuple(sorted(g for acl in acls.values() for g in acl)),
        )
        if menus
        else None
    )

    pw = (await _stdout(t, c.ROOT_PASSWORD_STATE) or "").strip()
    root_password: Literal["none", "set", "unknown"] = (
        "none" if pw == "none" else "set" if pw == "set" else "unknown"
    )

    return SelfDescription(
        identity=identity,
        board=board,
        services=services,
        features=features,
        protocols=protocols,
        wireless_options=wireless_options,
        luci=luci,
        root_password=root_password,
        read_at=datetime.now().astimezone(),
    )


def propose_port_labels(board: BoardInfo | None) -> dict[int, str]:
    if board is None:
        return {}
    return {p.num: p.label for p in board.ports if p.label}


def _flags(features: dict[str, Any] | None) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for key, value in (features or {}).items():
        if isinstance(value, bool):
            flags[key] = value
        elif key == "hostapd" and isinstance(value, dict):
            flags.update({k: v for k, v in value.items() if isinstance(v, bool) and k != "cli"})
    return flags


def summarize(d: SelfDescription) -> DescriptionSummary:
    return DescriptionSummary(
        model=d.board.model_name if d.board else d.identity.model,
        hostname=d.identity.hostname,
        revision=d.identity.revision,
        target=d.identity.target,
        services=len(d.services),
        protocols={name: len(opts) for name, opts in sorted(d.protocols.items())},
        wireless_options={
            radio: {g: len(opts) for g, opts in groups.items()}
            for radio, groups in d.wireless_options.items()
        },
        features_on=_flags(d.features),
        luci_packages=len(d.luci.packages) if d.luci else 0,
        luci_menu_entries=d.luci.menu_entries if d.luci else 0,
        port_labels=propose_port_labels(d.board),
    )
