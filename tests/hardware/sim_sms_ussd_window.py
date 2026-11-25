"""The 1.3b AP2 window's four parts as plain async functions, so the window test (test_ap2_lte_sim_sms_ussd)
and its offline twin (test_sim_sms_ussd_offline, on the simulator) run exactly the same code.

Nothing private is ever recorded (plan E13): a message becomes its shape, a send becomes ok / not ok, a USSD
reply becomes its status and length, a list becomes a count.

Each part writes its keys into the shared record as it reads them, so a failure keeps what came before it,
and an answer that does not parse is recorded as {"error": <constant text>} while the part goes on (final
review I5): a window is too rare to lose to the first unproven shape."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast, get_args

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.lte import commands as c
from openwrtgui.lte.commands import Storage
from openwrtgui.lte.modem import ModemService
from openwrtgui.lte.parse import parse_at
from openwrtgui.lte.service import SCREEN, LteService
from openwrtgui.lte.sms import parse_message

STORAGES: tuple[str, ...] = get_args(Storage)
_M_OF_STATUS = {"reply": 0, "more": 1, "ended": 2}  # +CUSD's m, where the status names it
NOT_PARSED = "the modem's answer did not parse"
NOT_GIVEN = "the modem did not give the message"
HALF_SEND = "--sms-to and --sms-text go together: give both to send an SMS, or neither"

Record = dict[str, object]


@dataclass(frozen=True)
class Options:
    """What the person named; a part with nothing named does not run."""

    read: tuple[Storage, int] | None = None
    delete: tuple[Storage, tuple[int, ...]] | None = None
    to: str | None = None
    text: str | None = None
    ussd: str | None = None


@dataclass(frozen=True)
class Window:
    modem: ModemService
    lte: LteService
    guard: BenchGuard
    audit: AuditLog
    router_id: str


def _storage(text: str) -> Storage:
    if text not in STORAGES:
        raise ValueError(f"storage {text!r} is not one of {STORAGES}")
    return cast(Storage, text)


def parse_read(value: str | None) -> tuple[Storage, int] | None:
    """`--sms-read <storage>:<id>`."""
    if value is None:
        return None
    storage, _, ident = value.partition(":")
    return _storage(storage), int(ident)


def parse_delete(value: str | None) -> tuple[Storage, tuple[int, ...]] | None:
    """`--sms-delete <storage>:<id>,<id>...`."""
    if value is None:
        return None
    storage, _, idents = value.partition(":")
    return _storage(storage), tuple(int(i) for i in idents.split(","))


async def _at_lines(w: Window, command: str) -> list[str]:
    """One AT query through the app's own path (AT lock, AT port, 2 s exchange), like ModemService's CPMS
    read: a read, not audited. The answer lines; empty when no port answered or the modem said ERROR."""
    rec, t, _device = await w.lte.connection(w.router_id)
    async with w.lte.at_lock(rec.id):
        port = await w.lte.at_port(rec, t)
        if port is None:
            return []
        result = await t.run(c.at(port, command))
        answer = parse_at(result.stdout, command) if result.ok else None
    return list(answer.lines) if answer is not None and answer.status == "OK" else []


async def _message(w: Window, rf: ModuleType, storage: Storage, ident: int, out: Record) -> None:
    """--get-message through run_audited (E5: audited, the command only), so its raw keys can be read. The
    keys and the message's shape are recorded each on its own: a message the modem does not give, or whose
    answer does not parse, is an error shape, and the window goes on."""
    rec, t, device = await w.lte.connection(w.router_id)
    result = await run_audited(
        t,
        c.get_message(device, storage, ident),
        router_id=rec.id,
        screen=SCREEN,
        guard=w.guard,
        audit=w.audit,
        require_guard=False,
    )
    if not result.ok:
        out["message"] = {"error": NOT_GIVEN}
        return
    try:
        raw = json.loads(result.stdout)
    except ValueError:
        raw = None
    out["message_keys"] = sorted(raw) if isinstance(raw, dict) else {"error": NOT_PARSED}
    message = parse_message(result.stdout, ident, storage)
    out["message"] = (
        rf.shape_only(dataclasses.asdict(message)) if message is not None else {"error": NOT_PARSED}
    )


async def part_reads(w: Window, rf: ModuleType, read: tuple[Storage, int] | None, out: Record) -> None:
    """Part 1: the SIM state, both lists, AT+CPMS?, one message (the named one, else the first SIM id) and the
    modem's AT+BMMODODR=? answer (E11, for O2), each written into `out` as soon as it is read."""
    try:
        out["sim"] = dataclasses.asdict(await w.modem.sim(w.router_id))
    except ValueError:  # the app's parse failure (NO_SIM_STATE)
        out["sim"] = {"error": NOT_PARSED}
    lists: Record = {}
    out["lists"] = lists
    first_sim: int | None = None
    for storage in STORAGES:
        try:
            listed = await w.modem.messages(w.router_id, _storage(storage))
        except ValueError:  # the app's parse failure (NO_MESSAGE_LIST)
            lists[storage] = {"error": NOT_PARSED}
            continue
        lists[storage] = {"count": len(listed.ids), "used": listed.used, "capacity": listed.capacity}
        if storage == "sim" and listed.ids:
            first_sim = listed.ids[0]
    for key, command in (("cpms", "AT+CPMS?"), ("bmmododr_test", "AT+BMMODODR=?")):
        lines = await _at_lines(w, command)
        out[key] = [rf.sanitize_modem(command, line) for line in lines]
    target = read if read is not None else (("sim", first_sim) if first_sim is not None else None)
    if target is not None:
        storage, ident = cast(tuple[Storage, int], target)
        await _message(w, rf, storage, ident, out)


async def part_delete(w: Window, storage: Storage, ids: tuple[int, ...], out: Record) -> None:
    """Part 2: delete the named ids through the preview and its digest, then count what is gone."""
    before = (await w.modem.messages(w.router_id, storage)).ids
    plan = await w.modem.plan_delete(w.router_id, storage, ids)
    done = await w.modem.delete(w.router_id, storage, ids, plan.digest)
    assert done.ok, "the modem did not delete the messages"
    after = (await w.modem.messages(w.router_id, storage)).ids
    out["deleted"] = len(before) - len(after)


async def part_send(w: Window, to: str, text: str, out: Record) -> None:
    """Part 3: send one SMS; only whether the modem took it is recorded, never the number or the text."""
    plan = await w.modem.plan_send(w.router_id, to, text)
    done = await w.modem.send(w.router_id, to, text, plan.digest)
    out["sent"] = {"ok": done.ok}


async def part_ussd(w: Window, code: str, out: Record) -> None:
    """Part 4: one USSD code; its status and the reply's length are recorded, never the code or the text."""
    plan = await w.modem.plan_ussd(w.router_id, code)
    reply = await w.modem.ussd(w.router_id, code, plan.digest)
    out["ussd"] = {
        "m": _M_OF_STATUS.get(reply.status),
        "dcs": reply.dcs,
        "status": reply.status,
        "text_chars": len(reply.text or ""),
        "closed": reply.closed,
    }


def check_options(opts: Options) -> None:
    """A send needs both its number and its text: one without the other is a usage error, never a part
    skipped in silence (final review I5)."""
    if (opts.to is None) != (opts.text is None):
        raise pytest.UsageError(HALF_SEND)


async def run_window(w: Window, rf: ModuleType, opts: Options, out: Path) -> Record:
    """Part 1 always; parts 2 to 4 only with their options. The options are checked before anything runs; then
    the file is written in a `finally`, with every key read until then, whatever the parts did."""
    check_options(opts)
    recorded: Record = {}
    try:
        await part_reads(w, rf, opts.read, recorded)
        if opts.delete is not None:
            await part_delete(w, *opts.delete, recorded)
        if opts.to is not None and opts.text is not None:
            await part_send(w, opts.to, opts.text, recorded)
        if opts.ussd is not None:
            await part_ussd(w, opts.ussd, recorded)
    finally:
        out.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    return recorded
