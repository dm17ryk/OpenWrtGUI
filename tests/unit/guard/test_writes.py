import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.guard.writes import WriteAction, perform_write, run_audited
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import CommandResult, Unreachable
from openwrtgui.transport.fake import ReplayTransport


def _clear_guard() -> BenchGuard:
    g = BenchGuard(GuardWatchList(lock_files=[], processes=[]), lister=lambda: [])
    g.check_local()
    return g


def _live_guard() -> BenchGuard:
    g = BenchGuard(
        GuardWatchList(lock_files=[], processes=["dima_night.py"]),
        lister=lambda: [ProcessInfo(1, ("dima_night.py",), datetime(2026, 11, 3, 21, 4))],
    )
    g.check_local()
    return g


def _ok(*cmds: str) -> dict[str, CommandResult]:
    return {c: CommandResult(c, "", "", 0) for c in cmds}


async def test_guard_live_blocks_and_runs_nothing(tmp_path: Path) -> None:
    t = ReplayTransport(_ok("uci commit"))
    action = WriteAction(router_id="ap2", screen="Wi-Fi", commands=("uci commit",))
    with pytest.raises(GuardLocked):
        await perform_write(
            action, transport=t, lock=asyncio.Lock(), guard=_live_guard(), audit=AuditLog(tmp_path)
        )
    assert t.calls == []


async def test_stops_at_first_failure_and_audits_masked(tmp_path: Path) -> None:
    cmds = {
        **_ok("uci set wireless.default_radio0.key='s3cret'", "wifi reload"),
        "uci commit wireless": CommandResult("uci commit wireless", "", "busy", 1),
    }
    t = ReplayTransport(cmds)
    action = WriteAction(
        router_id="ap2",
        screen="Wi-Fi",
        commands=("uci set wireless.default_radio0.key='s3cret'", "uci commit wireless", "wifi reload"),
        secrets=("s3cret",),
    )
    audit = AuditLog(tmp_path)
    results = await perform_write(action, transport=t, lock=asyncio.Lock(), guard=_clear_guard(), audit=audit)
    assert [r.exit_status for r in results] == [0, 1]
    entries = audit.query()
    assert [e.command for e in reversed(entries)] == [
        "uci set wireless.default_radio0.key='<hidden>'",
        "uci commit wireless",
    ]
    assert entries[0].exit_status == 1 and entries[0].router == "ap2" and entries[0].source == "user"


def test_preview_is_masked() -> None:
    action = WriteAction(router_id="ap2", screen="x", commands=("echo pw1 | passwd",), secrets=("pw1",))
    assert action.preview() == ["echo <hidden> | passwd"]


async def test_stdin_is_passed_for_single_command(tmp_path: Path) -> None:
    from openwrtgui.transport.fake import SimState

    state = SimState()
    t = ReplayTransport({}, state=state)
    action = WriteAction(
        router_id="new", screen="Add router", commands=("passwd root",), secrets=("pw1",), stdin="pw1\npw1\n"
    )
    await perform_write(
        action, transport=t, lock=asyncio.Lock(), guard=_clear_guard(), audit=AuditLog(tmp_path)
    )
    assert state.root_password == "pw1"


class SlowTransport(ReplayTransport):
    def __init__(self, log: list[str]) -> None:
        super().__init__({})
        self.log = log

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.log.append(f"start {command}")
        await asyncio.sleep(0.05)
        self.log.append(f"end {command}")
        return CommandResult(command, "", "", 0)


async def test_writes_to_one_router_are_serialized(tmp_path: Path) -> None:
    log: list[str] = []
    t = SlowTransport(log)
    lock = asyncio.Lock()
    audit, guard = AuditLog(tmp_path), _clear_guard()
    a = WriteAction(router_id="ap2", screen="x", commands=("a",))
    b = WriteAction(router_id="ap2", screen="x", commands=("b",))
    await asyncio.gather(
        perform_write(a, transport=t, lock=lock, guard=guard, audit=audit),
        perform_write(b, transport=t, lock=lock, guard=guard, audit=audit),
    )
    assert log == ["start a", "end a", "start b", "end b"]


async def test_run_audited_masks_secrets_and_refuses_when_guard_live(tmp_path: Path) -> None:
    cmd = "uci set wireless.default_radio0.key='s3cret-key'"
    t = ReplayTransport(_ok(cmd))
    audit = AuditLog(tmp_path)
    with pytest.raises(GuardLocked):
        await run_audited(t, cmd, router_id="ap2", screen="Wi-Fi", guard=_live_guard(), audit=audit)
    assert t.calls == [] and audit.query() == []
    result = await run_audited(
        t, cmd, router_id="ap2", screen="Wi-Fi", guard=_clear_guard(), audit=audit, secrets=("s3cret-key",)
    )
    assert result.ok
    [entry] = audit.query()
    assert entry.command == "uci set wireless.default_radio0.key='<hidden>'"
    assert entry.exit_status == 0 and entry.source == "user" and entry.screen == "Wi-Fi"


class DeadTransport(ReplayTransport):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        raise Unreachable("192.168.1.2:22: connection lost")


async def test_run_audited_records_transport_failure(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path)
    with pytest.raises(Unreachable):
        await run_audited(
            DeadTransport({}),
            "wifi up radio0",
            router_id="ap2",
            screen="Wi-Fi",
            guard=_clear_guard(),
            audit=audit,
        )
    [entry] = audit.query()
    assert entry.command == "wifi up radio0" and entry.exit_status is None


async def test_reads_do_not_wait_for_the_write_lock(tmp_path: Path) -> None:
    log: list[str] = []
    t = SlowTransport(log)
    lock = asyncio.Lock()
    write = asyncio.create_task(
        perform_write(
            WriteAction(router_id="ap2", screen="x", commands=("w",)),
            transport=t,
            lock=lock,
            guard=_clear_guard(),
            audit=AuditLog(tmp_path),
        )
    )
    await asyncio.sleep(0.01)
    await t.run("r")
    await write
    assert log.index("start r") < log.index("end w")
