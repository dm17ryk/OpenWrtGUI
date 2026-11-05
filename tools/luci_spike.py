"""O13: does LuCI accept an rpcd session the app makes over SSH, with no password?

Read-only. It makes a read-only session with the LuCI bridge's own commands, forwards the router's web
server through SSH, fetches one LuCI page with the session cookie, makes two of the page's own ubus
calls, and destroys the session. If the page shows its login form or the calls are refused, it tries
once more with every access group (still read-only), as rpcd's own login does for root. It refuses any
host but AP2 (192.168.1.2) unless --allow-other is given, and writes what it saw to build/o13.json.

    uv run python tools/luci_spike.py --host 192.168.1.2 --identity <key the router accepts>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from openwrtgui.luci_bridge.session import (
    create_command,
    destroy_command,
    grant_commands,
    page_groups,
    set_command,
)
from openwrtgui.luci_bridge.upstream import ROUTER_WEB
from openwrtgui.probe.describe import describe_router
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

AP2 = "192.168.1.2"
PAGE = "admin/network/wireless"
OUT = Path(__file__).resolve().parents[1] / "build" / "o13.json"
DENIED = -32002  # rpcd's JSON-RPC "Access denied"
CALLS = (("iwinfo", "assoclist", {"device": "phy0-ap0"}), ("uci", "get", {"config": "wireless"}))


def has_login_form(html: str) -> bool:
    return 'name="luci_password"' in html


def ubus_body(sid: str, obj: str, method: str, args: dict[str, Any]) -> str:
    """One call the way LuCI's own pages make it (POST /ubus/, JSON-RPC with the session id)."""
    return json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "call", "params": [sid, obj, method, args]}])


def ubus_outcome(reply: Any) -> str:
    """'denied' when rpcd refused the session; otherwise allowed, with ubus's own status when not 0."""
    if not isinstance(reply, list) or not reply or not isinstance(reply[0], dict):
        return "unreadable"
    answer = reply[0]
    if "error" in answer:
        return "denied" if answer["error"].get("code") == DENIED else f"error {answer['error']}"
    status = (answer.get("result") or [None])[0]
    return "allowed" if status == 0 else f"allowed (ubus status {status})"


async def _session(t: SshTransport, groups: list[str], acl: dict[str, Any]) -> str:
    created = await t.run(create_command())
    sid = str(json.loads(created.stdout)["ubus_rpc_session"])
    for command in [*grant_commands(sid, groups, acl, "read"), set_command(sid, secrets.token_hex(16))]:
        r = await t.run(command)
        if not r.ok:
            raise RuntimeError(f"{command.split(' {')[0]} failed: {r.stderr.strip()}")
    return sid


async def _attempt(
    t: SshTransport, port: int, label: str, groups: list[str], acl: dict[str, Any]
) -> dict[str, Any]:
    sid = await _session(t, groups, acl)
    try:
        cookie = {"Cookie": f"sysauth_http={sid}; sysauth={sid}"}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20.0) as client:
            page = await client.get(f"/cgi-bin/luci/{PAGE}", headers=cookie)
            calls = {}
            for obj, method, args in CALLS:
                r = await client.post("/ubus/", content=ubus_body(sid, obj, method, args))
                try:
                    calls[f"{obj} {method}"] = ubus_outcome(r.json())
                except ValueError:
                    calls[f"{obj} {method}"] = f"HTTP {r.status_code}, not JSON"
        return {
            "attempt": label,
            "groups": groups,
            "status": page.status_code,
            "login_form": has_login_form(page.text),
            "calls": calls,
        }
    finally:
        await t.run(destroy_command(sid))


async def spike(host: str, identity: Path, known_hosts: Path) -> dict[str, Any]:
    info = await fetch_host_key(host)
    print(f"{host} host key {info.type} {info.fingerprint} (pinned for this run only)")
    keys = HostKeyStore(known_hosts)
    keys.pin(host, 22, info)
    t = await SshTransport.connect(host, 22, "root", host_keys=keys, key_paths=[identity])
    try:
        desc = await describe_router(t)
        if desc.luci is None:
            raise RuntimeError("the router has no LuCI menu")
        page = next(p for p in desc.luci.pages if p.path == PAGE)
        acl = desc.luci.acl
        forward = await t.forward_local(*ROUTER_WEB)
        try:
            attempts = [await _attempt(t, forward.port, "page groups", page_groups(page, acl), acl)]
            first = attempts[0]
            if first["login_form"] or "denied" in first["calls"].values():
                attempts.append(await _attempt(t, forward.port, "every group, read", sorted(acl), acl))
        finally:
            await forward.close()
    finally:
        await t.close()
    return {
        "host": host,
        "page": PAGE,
        "at": datetime.now().isoformat(timespec="seconds"),
        "attempts": attempts,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=AP2)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--allow-other", action="store_true")
    args = ap.parse_args(argv)
    if args.host != AP2 and not args.allow_other:
        print(f"refusing {args.host}: only AP2 ({AP2}) without --allow-other", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(spike(args.host, args.identity, Path(tmp) / "known_hosts"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for a in result["attempts"]:
        print(f"{a['attempt']}: HTTP {a['status']}, login form {a['login_form']}, calls {a['calls']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
