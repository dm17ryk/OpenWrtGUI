"""System › Plugins (v1.0a2 D4): LuCI's plugin switches in /etc/config/luci_plugins.

A plugin is a JS file in PLUGIN_DIR named by its 32-hex id; its `baseclass.extend({...})` names its class
and type (http/headers, auth/login, ...). luci_plugins holds `global` (`enabled`, `<class>_<type>_enabled`)
and one section per plugin, named by its id, of type `<class>_<type>`. A plugin's own form is JS code: its
options are shown, and edited in LuCI.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence, Set

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import HIDDEN
from openwrtgui.system.commands import PLUGIN_DIR
from openwrtgui.uci import UciOp

PLUGIN_ID = re.compile(r"[0-9a-f]{32}")
PLUGIN_FILE = re.compile(r"([0-9a-f]{32})\.js")
_WORD = re.compile(r"[a-z][a-z0-9]{0,31}")  # a plugin class or type
# `key: 'literal'` or `key: _('literal')`, single or double quotes; the first of each key wins
_FIELD = re.compile(
    r"""\b(class|type|name|id|title|description)\s*:\s*(?:_\(\s*)?(['"])((?:(?!\2).){0,300})\2"""
)
# a plugin's option that may hold a secret (LuCI's 2FA plugin keeps root's TOTP key in key_root): never shown
_SECRET_OPTION = re.compile(r"key|secret|pass|token|pin", re.IGNORECASE)
LOGIN_WARNING = (
    "A login plugin adds a step to LuCI's web login on this router. The LuCI pages in this app log in over "
    "SSH and are not affected."
)


class PluginHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    class_name: str
    type_name: str
    name: str
    title: str
    description: str


class PluginRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    group: str  # `<class>_<type>`: the section type and the global switch's prefix
    name: str
    title: str
    description: str
    installed: bool  # its JS file is there
    readable: bool  # its header could be read (title, class and type); else it is configured in LuCI
    configured: bool  # it has a section
    enabled: bool  # LuCI runs it (header plugins: any `enabled` value; login plugins: '1')
    options: dict[str, str]  # its own options, shown (secret ones hidden); edited in LuCI


class PluginGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    enabled: bool


class PluginState(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    global_section: bool
    groups: list[PluginGroup]
    plugins: list[PluginRow]
    missing: tuple[str, ...] = ()  # "luci_plugins config": the router has no such config


class PluginChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool | None = None  # the global switch; None leaves it
    groups: dict[str, bool] = {}
    plugins: dict[str, bool] = {}
    remove: list[str] = []  # sections whose plugin file is gone


def read_plugin_command(file_id: str) -> str:
    if not PLUGIN_ID.fullmatch(file_id):
        raise ValueError(f"{file_id!r} is not a plugin id")
    return f"cat {PLUGIN_DIR}/{file_id}.js"


def parse_header(file_id: str, text: str) -> PluginHeader | None:
    """The literal fields of a plugin's declaration. None when it names no class or type (no group)."""
    found: dict[str, str] = {}
    for m in _FIELD.finditer(text):
        found.setdefault(m.group(1), m.group(3))
    cls, typ = found.get("class", ""), found.get("type", "")
    if not (_WORD.fullmatch(cls) and _WORD.fullmatch(typ)):
        return None
    return PluginHeader(
        id=file_id,
        class_name=cls,
        type_name=typ,
        name=found.get("name", file_id),
        title=found.get("title", ""),
        description=found.get("description", ""),
    )


def _runs(group: str, value: str | None) -> bool:
    # luciplugins.uc: a login plugin loads only with enabled == "1"; header plugins run on any value (truthy)
    return value == "1" if group.startswith("auth_") else bool(value)


def plugin_state(
    uci: Mapping[str, str], headers: Sequence[PluginHeader], files: Set[str] | None = None
) -> PluginState:
    """`files`: the plugin ids whose JS file the router lists (default: the ones whose header was read). A
    file whose header cannot be read is still installed (final review): shown, and configured in LuCI."""
    by_id = {h.id: h for h in headers}
    present = set(files) if files is not None else set(by_id)
    sections = {k.split(".", 1)[1]: v for k, v in uci.items() if k.count(".") == 1}
    rows: list[PluginRow] = []
    for pid in sorted(present | set(by_id) | {n for n in sections if PLUGIN_ID.fullmatch(n)}):
        h = by_id.get(pid)
        group = f"{h.class_name}_{h.type_name}" if h else sections.get(pid, "")
        prefix = f"luci_plugins.{pid}."
        opts = {k.removeprefix(prefix): v for k, v in uci.items() if k.startswith(prefix)}
        rows.append(
            PluginRow(
                id=pid,
                group=group,
                name=opts.get("name") or (h.name if h else pid),
                title=h.title if h else "",
                description=h.description if h else "",
                installed=pid in present,
                readable=h is not None,
                configured=pid in sections,
                enabled=_runs(group, opts.get("enabled")),
                options={
                    k: HIDDEN if _SECRET_OPTION.search(k) else v
                    for k, v in opts.items()
                    if k not in ("name", "enabled")
                },
            )
        )
    groups = sorted({r.group for r in rows if r.group})
    return PluginState(
        enabled=uci.get("luci_plugins.global.enabled") == "1",
        global_section="luci_plugins.global" in uci,
        groups=[
            PluginGroup(key=g, enabled=uci.get(f"luci_plugins.global.{g}_enabled") == "1") for g in groups
        ],
        plugins=rows,
    )


def _switch(path: str, on: bool) -> UciOp:
    # Off deletes: a header plugin with enabled='0' would still run (D4)
    return UciOp("set", path, "1") if on else UciOp("delete", path)


def plugin_ops(state: PluginState, change: PluginChange) -> list[UciOp]:
    """Group keys and plugin ids reach a uci path unquoted: they come only from the router's own section types
    and from _WORD / PLUGIN_ID, and every key of the change is checked against them first."""
    rows = {r.id: r for r in state.plugins}
    groups = {g.key for g in state.groups}
    ops: list[UciOp] = []
    if (change.enabled is not None or change.groups) and not state.global_section:
        ops.append(UciOp("set", "luci_plugins.global", "global"))
    if change.enabled is not None:
        ops.append(_switch("luci_plugins.global.enabled", change.enabled))
    for key, on in change.groups.items():
        if key not in groups:
            raise ValueError(f"No plugin group {key} on this router")
        ops.append(_switch(f"luci_plugins.global.{key}_enabled", on))
    for pid, on in change.plugins.items():
        row = rows.get(pid)
        if row is None or not row.installed:
            raise ValueError(f"No installed plugin {pid} on this router")
        if not row.group:
            raise ValueError(f"The header of plugin {pid} could not be read: configure it in LuCI")
        if on and not row.configured:
            ops += [
                UciOp("set", f"luci_plugins.{pid}", row.group),
                UciOp("set", f"luci_plugins.{pid}.name", row.name),
            ]
        ops.append(_switch(f"luci_plugins.{pid}.enabled", on))
    for pid in change.remove:
        row = rows.get(pid)
        if row is None or row.installed or not row.configured:
            raise ValueError(f"Only a plugin whose file is gone can be removed ({pid})")
        ops.append(UciOp("delete", f"luci_plugins.{pid}"))
    return ops
