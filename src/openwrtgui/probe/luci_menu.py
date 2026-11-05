"""LuCI's own page list (menu.d) and access groups (rpcd acl.d), as the router has them installed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PAGE_ACTIONS = frozenset({"view", "template", "cbi", "form"})
SECTION_SEP = " › "


@dataclass(frozen=True)
class LuciPage:
    path: str
    title: str
    package: str
    acl: tuple[str, ...]
    uci: tuple[str, ...]
    fs: tuple[str, ...]
    section: str = ""  # the menu entries above the page, below "admin": "Network › Firewall"


def _names(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(k) for k in value)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def _section(path: str, titles: Mapping[str, str]) -> str:
    parts = path.split("/")
    above = ("/".join(parts[:n]) for n in range(2, len(parts)))
    return SECTION_SEP.join(titles.get(p, p.rsplit("/", 1)[-1]) for p in above)


def parse_menu(menus: Mapping[str, Mapping[str, Any]]) -> list[LuciPage]:
    """Every menu entry that shows a page, from {menu.d file stem: its JSON}."""
    titles = {
        path: str(entry["title"])
        for entries in menus.values()
        for path, entry in entries.items()
        if isinstance(entry, dict) and entry.get("title")
    }
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
                    section=_section(path, titles),
                )
            )
    return sorted(pages, key=lambda p: p.path)


def _merge(into: Any, more: Any) -> Any:
    """Dicts merge per key, lists keep every item once (first order kept); anything else: the later value."""
    if isinstance(into, dict) and isinstance(more, dict):
        out = dict(into)
        for key, value in more.items():
            out[key] = _merge(out[key], value) if key in out else value
        return out
    if isinstance(into, list) and isinstance(more, list):
        return [*into, *(v for v in more if v not in into)]
    return more


def parse_acl(acls: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """{access group: its definition} from every acl.d file. A group defined in several files gets all of
    them, as rpcd applies them (luci-base.json and unauthenticated.json both define `unauthenticated`)."""
    groups: dict[str, dict[str, Any]] = {}
    for definitions in acls.values():
        for name, definition in definitions.items():
            if isinstance(definition, dict):
                groups[name] = _merge(groups[name], definition) if name in groups else definition
    return groups
