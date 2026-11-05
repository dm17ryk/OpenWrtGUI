"""O14: does rpcd's `uci apply` (rollback) and `uci confirm` work from SSH, as LuCI's own apply does?

It changes only a throwaway config, /etc/config/owgprobe, which no service reads, and reloads nothing:

- round 1: stage a value in an rpcd session, `uci apply` with a 10 s rollback, read it, wait 15 s, read
  again (expect it rolled back);
- round 2: the same with 30 s, then close the SSH connection, open a new one, `uci confirm`, wait 35 s,
  read (expect it kept).

The file and both sessions are removed at the end, whatever happened. AP2 (192.168.1.2) only.

    uv run python tools/rollback_spike.py --identity C:/Essence_SC/home/.ssh/id_rsa \
        --known-hosts C:/Essence_SC/home/.ssh/known_hosts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.luci_bridge.session import create_command, destroy_command
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import CommandResult, ubus_command
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import UciOp, render_uci

AP2 = "192.168.1.2"
CONFIG = "owgprobe"
TOUCH = f"touch /etc/config/{CONFIG}"
REMOVE = f"rm -f /etc/config/{CONFIG}"
READ = f"uci -q get {CONFIG}.t.v"
OUT = Path(__file__).resolve().parents[1] / "build" / "o14.json"


class Conn(Protocol):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult: ...
    async def close(self) -> None: ...


Connect = Callable[[], Awaitable[Conn]]
Sleep = Callable[[float], Awaitable[None]]


class _Probe:
    def __init__(self, connect: Connect, sleep: Sleep) -> None:
        self.connect = connect
        self.sleep = sleep
        self.conn: Conn | None = None
        self.steps: list[dict[str, Any]] = []

    async def run(self, command: str) -> CommandResult:
        assert self.conn is not None
        r = await self.conn.run(command, timeout=30.0)
        self.steps.append({"command": command, "exit": r.exit_status, "stdout": r.stdout, "stderr": r.stderr})
        return r

    async def reconnect(self) -> None:
        if self.conn is not None:
            await self.conn.close()
        self.conn = await self.connect()

    async def session(self) -> str:
        sid = str(json.loads((await self.run(create_command())).stdout)["ubus_rpc_session"])
        objects = [[CONFIG, "read"], [CONFIG, "write"]]
        await self.run(
            ubus_command("session", "grant", {"objects": objects, "scope": "uci", "ubus_rpc_session": sid})
        )
        savedir = f"/var/run/rpcd/uci-{sid}"
        await self.run(f"mkdir -p {savedir}")
        for line in render_uci(
            [UciOp("set", f"{CONFIG}.t", "probe"), UciOp("set", f"{CONFIG}.t.v", "1")], savedir
        ):
            await self.run(line)
        return sid

    async def apply(self, sid: str, timeout: int) -> CommandResult:
        return await self.run(
            ubus_command("uci", "apply", {"rollback": True, "timeout": timeout, "ubus_rpc_session": sid})
        )

    async def value(self) -> str:
        return (await self.run(READ)).stdout.strip()


def _reason(r: CommandResult) -> str:
    return (r.stderr or r.stdout).strip() or f"exit {r.exit_status}"


async def _round1(p: _Probe) -> dict[str, Any]:
    sid = await p.session()
    try:
        applied = await p.apply(sid, 10)
        if not applied.ok:
            return {"applied": False, "error": _reason(applied)}
        seen = await p.value()
        await p.sleep(15)
        return {"applied": seen == "1", "rolled_back": await p.value() == ""}
    finally:
        await p.run(destroy_command(sid))


async def _round2(p: _Probe) -> dict[str, Any]:
    sid = await p.session()
    try:
        applied = await p.apply(sid, 30)
        if not applied.ok:
            return {"applied": False, "error": _reason(applied)}
        await p.reconnect()  # the app confirms from a new connection after the change
        await p.run(ubus_command("uci", "confirm", {"ubus_rpc_session": sid}))
        await p.sleep(35)
        return {"applied": True, "kept_after_reconnect": await p.value() == "1"}
    finally:
        await p.run(destroy_command(sid))


async def spike(connect: Connect, sleep: Sleep) -> dict[str, Any]:
    p = _Probe(connect, sleep)
    findings: dict[str, Any] = {}
    await p.reconnect()
    try:
        await p.run(TOUCH)
        findings["round1"] = await _round1(p)
        if findings["round1"]["applied"]:
            findings["round2"] = await _round2(p)
    finally:
        await p.run(REMOVE)
        if p.conn is not None:
            await p.conn.close()
    findings["steps"] = p.steps
    return findings


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=AP2)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--known-hosts", type=Path, default=Path.home() / ".ssh" / "known_hosts")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.host != AP2:
        print(f"refusing {args.host}: only AP2 ({AP2})", file=sys.stderr)
        return 2
    state = BenchGuard(GuardWatchList()).check_local()
    if state.live:
        print("Bench Guard sees a run: " + "; ".join(r.text for r in state.reasons), file=sys.stderr)
        return 3

    async def connect() -> Conn:
        # The router's key must already be in known_hosts (checked by the user); never pinned here.
        return await SshTransport.connect(
            args.host, 22, "root", host_keys=HostKeyStore(args.known_hosts), key_paths=[args.identity]
        )

    findings = asyncio.run(spike(connect, asyncio.sleep))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in findings.items() if k != "steps"}))
    print(f"steps in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
