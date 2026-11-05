"""LuCI's own page list (menu.d) and access groups (rpcd acl.d), as the router has them installed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PAGE_ACTIONS = frozenset({"view", "template", "cbi", "form"})


@dataclass(frozen=True)
class LuciPage:
    path: str
    title: str
    package: str
    acl: tuple[str, ...]
    uci: tuple[str, ...]
    fs: tuple[str, ...]


def _names(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(k) for k in value)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def parse_menu(menus: Mapping[str, Mapping[str, Any]]) -> list[LuciPage]:
    """Every menu entry that shows a page, from {menu.d file stem: its JSON}."""
    pages = []
    for package, entries in menus.items():
        for path, entry in entries.items():
            if not isinstance(entry, dict) or (entry.get("action") or {}).get("type") not in PAGE_ACTIONS:
                continue
            depends = entry.get("depends") or {}
            pages.append(
                LuciPage(
                    path=path,
                    title=str(entry.get("title") or path.rsplit("/", 1)[-1]),
                    package=package,
                    acl=_names(depends.get("acl")),
                    uci=_names(depends.get("uci")),
                    fs=_names(depends.get("fs")),
                )
            )
    return sorted(pages, key=lambda p: p.path)


def parse_acl(acls: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """{access group: its definition} from every acl.d file."""
    groups: dict[str, dict[str, Any]] = {}
    for definitions in acls.values():
        for name, definition in definitions.items():
            if isinstance(definition, dict):
                groups[name] = definition
    return groups
