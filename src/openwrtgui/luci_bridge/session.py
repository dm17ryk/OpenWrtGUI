"""The rpcd session a LuCI fallback page runs in, made over SSH (`ubus call session …`), no password.

The grants mirror what rpcd's own login gives for the page's access groups (acl.d): `read` only during a
harness run, `read` + `write` otherwise. The session lives in rpcd's memory only and expires when idle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from openwrtgui.probe.luci_menu import LuciPage
from openwrtgui.transport.base import ubus_command

SESSION_TIMEOUT_S = 300
# Every LuCI page also needs LuCI's own base calls (menu, status header).
BASE_GROUPS = ("luci-base", "luci-base-network-status", "unauthenticated")
Access = Literal["read", "write"]


def create_command() -> str:
    return ubus_command("session", "create", {"timeout": SESSION_TIMEOUT_S})


def page_groups(page: LuciPage, acl: Mapping[str, Any]) -> list[str]:
    """The page's access groups (or its package's, when the menu entry names none), then LuCI's base."""
    own = list(page.acl) or ([page.package] if page.package in acl else [])
    return [g for g in dict.fromkeys([*own, *BASE_GROUPS]) if g in acl]


def _objects(scope: str, block: Mapping[str, Any], level: Access) -> list[list[str]]:
    value = block.get(scope)
    if scope == "ubus" and isinstance(value, dict):
        return [[obj, str(m)] for obj, methods in value.items() for m in methods]
    if scope == "uci" and isinstance(value, list):
        return [[str(cfg), level] for cfg in value]
    if scope == "file" and isinstance(value, dict):
        return [[path, str(op)] for path, ops in value.items() for op in ops]
    if scope == "cgi-io" and isinstance(value, list):
        return [[str(op), level] for op in value]
    return []


def grant_commands(
    sid: str, groups: Sequence[str], acl: Mapping[str, Mapping[str, Any]], access: Access
) -> list[str]:
    levels: list[Access] = ["read", "write"] if access == "write" else ["read"]
    scopes: dict[str, list[list[str]]] = {"access-group": []}
    for group in groups:
        definition = acl.get(group)
        if definition is None:
            continue
        for level in levels:
            scopes["access-group"].append([group, level])
            block = definition.get(level) or {}
            for scope in ("ubus", "uci", "file", "cgi-io"):
                for obj in _objects(scope, block, level):
                    if obj not in scopes.setdefault(scope, []):
                        scopes[scope].append(obj)
    return [
        ubus_command("session", "grant", {"objects": objs, "scope": scope, "ubus_rpc_session": sid})
        for scope, objs in scopes.items()
        if objs
    ]


def set_command(sid: str, token: str) -> str:
    """LuCI accepts a session with a user name and a CSRF token (luci dispatcher, session_retrieve)."""
    return ubus_command(
        "session", "set", {"ubus_rpc_session": sid, "values": {"token": token, "username": "root"}}
    )


def destroy_command(sid: str) -> str:
    return ubus_command("session", "destroy", {"ubus_rpc_session": sid})
