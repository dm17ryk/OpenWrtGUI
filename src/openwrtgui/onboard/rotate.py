"""App key rotation (spec 7.12, v1.1b D8): each router moves to the new key in three steps.

1. Add the new key's line (the wizard's own append, which never adds a line twice).
2. Prove a login with the new key only, over a new connection that refuses trivial auth.
3. Remove the old key's exact line: one command checks the new line is there, writes the file without the old
   lines into a temporary file and renames it over `authorized_keys` (ruling R5). The file is read back.

A router that fails keeps both lines or only the old one, so the app can always still log in.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.onboard.wizard import AUTHORIZED_KEYS, Connector, install_key_command
from openwrtgui.store.keys import AppKeyRing
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import AuthFailed, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Settings › App key rotation"
KEYS_READ = f"cat {AUTHORIZED_KEYS}"


class MoveFailed(Exception):
    """A router did not move to the new key; the message is its row's detail in Settings."""


def remove_old_key_command(new_line: str, old_line: str) -> str:
    """Remove every line exactly equal to `old_line`, only if `new_line` is there; atomic on the router."""
    new, old, ak = shlex.quote(new_line), shlex.quote(old_line), AUTHORIZED_KEYS
    tmp = f"{ak}.owg"
    return f"grep -qxF {new} {ak} && grep -vxF {old} {ak} > {tmp} && chmod 600 {tmp} && mv -f {tmp} {ak}"


def _lines(text: str) -> list[str]:
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n") if text else []


async def _read_keys(t: Transport, rec: RouterRecord) -> list[str]:
    result = await t.run(KEYS_READ)
    if not result.ok:
        raise MoveFailed(f"authorized_keys on {rec.name} is not as expected: check it on System › Access")
    return _lines(result.stdout)


async def _prove(rec: RouterRecord, keys: AppKeyRing, connector: Connector) -> None:
    assert keys.next is not None  # noqa: S101 - move_router checks it
    t = await connector.connect(
        rec.host,
        rec.port,
        password=None,
        key_paths=[keys.next.private_path],
        username=rec.username,
        prove=True,
    )
    try:
        if not (await t.run("true")).ok:
            raise AuthFailed(f"{rec.host} accepted the key but did not run a command")
    finally:
        await t.close()


async def move_router(
    rec: RouterRecord,
    *,
    keys: AppKeyRing,
    pool: ConnectionPool,
    connector: Connector,
    guard: BenchGuard,
    audit: AuditLog,
    on_step: Callable[[str], None],
) -> None:
    """Move one router to the next key (D8). Raises MoveFailed with the row's detail; GuardLocked passes."""
    nxt = keys.next
    if nxt is None:
        raise ValueError("No key rotation is under way")
    old = keys.current.public_line
    did_not_answer = f"{rec.name} did not answer: it stays on the old key"
    async with pool.write_lock(rec.id):
        try:
            on_step("adding")
            t = await pool.get(rec)
            added = await run_audited(
                t,
                install_key_command(nxt.public_line),
                router_id=rec.id,
                screen=SCREEN,
                guard=guard,
                audit=audit,
            )
            if not added.ok:
                raise MoveFailed(
                    f"{rec.name} did not take the new key: {added.stderr.strip() or 'no reason given'}"
                )
            on_step("proving")
            try:
                await _prove(rec, keys, connector)
            except AuthFailed as exc:
                raise MoveFailed(f"{rec.name} did not accept the new key: the old key stays") from exc
            on_step("removing")
            before = await _read_keys(t, rec)
            expected = [line for line in before if line != old]
            removed = await run_audited(
                t,
                remove_old_key_command(nxt.public_line, old),
                router_id=rec.id,
                screen=SCREEN,
                guard=guard,
                audit=audit,
            )
            after = await _read_keys(t, rec)
        except TransportError as exc:
            raise MoveFailed(did_not_answer) from exc
        if not removed.ok or after != expected or nxt.public_line not in after:
            raise MoveFailed(f"authorized_keys on {rec.name} is not as expected: check it on System › Access")
        n = len(before) - len(expected)
        audit.record(
            router=rec.id,
            screen=SCREEN,
            command="check authorized_keys",
            exit_status=0,
            verify=f"new key logs in; {n} old line(s) removed; other lines unchanged",
            source="user",
        )
        keys.mark_moved(rec.id)
    await pool.drop(rec.id)
