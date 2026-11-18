"""#4 (the v1.0 inventory): the app's own ingress qdisc showed as "unknown" on the Firewall screen."""

from __future__ import annotations

import pytest
from readcount import commands_of

from openwrtgui.context import AppContext
from openwrtgui.fw import commands as c
from openwrtgui.probe.commands import FAULT_RECORDS
from openwrtgui.transport.base import CommandResult

QDISCS = (
    "qdisc noqueue 0: dev lo root refcnt 2\n"
    "qdisc ingress ffff: dev eth0.1 parent ffff:fff1 ----------------\n"
)
RECORD = (
    '{"id":"f1","kind":"shape","clear":["tc qdisc del dev eth0.1 ingress","ip link del owgifb0"],'
    '"armed_at":1}\n'
)


async def _answers(ctx: AppContext, monkeypatch: pytest.MonkeyPatch, qdiscs: str, records: str) -> None:
    rec = ctx.routers.get("ap2")
    assert rec is not None
    t = await ctx.pool.get(rec)
    original = t.run

    async def run(command: str, *, timeout: float = 15.0) -> CommandResult:
        if command == c.TC_QDISCS:
            t.calls.append(command)  # type: ignore[attr-defined]
            return CommandResult(command, qdiscs, "", 0)
        if command == FAULT_RECORDS:
            t.calls.append(command)  # type: ignore[attr-defined]
            return CommandResult(command, records, "", 0 if records else 1)
        return await original(command, timeout=timeout)

    monkeypatch.setattr(t, "run", run)


async def test_an_ingress_named_by_an_armed_fault_is_the_apps(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _answers(ctx, monkeypatch, QDISCS, RECORD)
    state = await ctx.fw.state("ap2")
    assert [(h.dev, h.kind, h.owner) for h in state.tc] == [("eth0.1", "ingress", "app")]


async def test_an_ingress_no_fault_names_stays_unknown(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _answers(ctx, monkeypatch, QDISCS, "")
    state = await ctx.fw.state("ap2")
    assert [(h.dev, h.kind, h.owner) for h in state.tc] == [("eth0.1", "ingress", "unknown")]


async def test_no_ingress_reads_no_fault_records(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: the records are read only when an ingress qdisc is listed, so a normal read costs nothing more."""
    await _answers(ctx, monkeypatch, "qdisc noqueue 0: dev lo root refcnt 2\n", RECORD)
    await ctx.fw.state("ap2")
    assert FAULT_RECORDS not in await commands_of(ctx, "ap2")
