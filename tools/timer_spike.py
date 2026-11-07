"""O15: does a router-side timer outlive the SSH connection, and can a new connection cancel it?

It changes only a throwaway file, /tmp/owg-spike (RAM), and reloads nothing:

- round 1: touch the file, arm a 10 s timer that removes it, close the SSH connection, open a new one 15 s
  later: expect the file gone (the timer ran after the PC went away);
- round 2: touch it again, arm a 30 s timer, close, open a new connection, cancel the timer, wait 35 s:
  expect the file still there.

The file and the timers' pid files are removed at the end, whatever happened. AP2 (192.168.1.2) only.

    uv run python tools/timer_spike.py --identity C:/Essence_SC/home/.ssh/id_rsa \
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
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.timer import arm_command, cancel_command
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.ssh import HostKeyStore, SshTransport

AP2 = "192.168.1.2"
FILE = "/tmp/owg-spike"
TOUCH = f"touch {FILE}"
REMOVE = f"rm -f {FILE}"
TEST = f"[ -e {FILE} ] && echo present || echo gone"
CLEANUP = f"rm -f {FILE} /tmp/owg/spike*"
OUT = Path(__file__).resolve().parents[1] / "build" / "o15.json"


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

    async def file(self) -> str:
        return (await self.run(TEST)).stdout.strip()


def _reason(r: CommandResult) -> str:
    return (r.stderr or r.stdout).strip() or f"exit {r.exit_status}"


async def _round1(p: _Probe) -> dict[str, Any]:
    await p.run(TOUCH)
    armed = await p.run(arm_command("spike1", 10, [REMOVE]))
    if not armed.ok:
        return {"armed": False, "error": _reason(armed)}
    await p.reconnect()  # the PC goes away; the timer must not care
    await p.sleep(15)
    return {"armed": True, "fired_after_disconnect": await p.file() == "gone"}


async def _round2(p: _Probe) -> dict[str, Any]:
    await p.run(TOUCH)
    armed = await p.run(arm_command("spike2", 30, [REMOVE]))
    if not armed.ok:
        return {"armed": False, "error": _reason(armed)}
    await p.reconnect()  # the app confirms from a new connection after the change
    await p.run(cancel_command("spike2"))
    await p.sleep(35)
    return {"armed": True, "cancelled_from_new_connection": await p.file() == "present"}


async def spike(connect: Connect, sleep: Sleep) -> dict[str, Any]:
    p = _Probe(connect, sleep)
    findings: dict[str, Any] = {}
    await p.reconnect()
    try:
        findings["round1"] = await _round1(p)
        if findings["round1"]["armed"]:
            findings["round2"] = await _round2(p)
    finally:
        await p.run(CLEANUP)
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
