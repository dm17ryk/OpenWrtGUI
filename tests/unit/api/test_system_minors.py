"""The v0.6b whole-branch review's deferred minors (v0.6c plan Task 16, D14), each pinned by a test."""

from __future__ import annotations

import asyncio
import gzip
import threading
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui import simsystem
from openwrtgui.context import AppContext
from openwrtgui.system import backup as backup_module
from openwrtgui.system import commands as s
from openwrtgui.system.backup import backup_dir, backup_name
from openwrtgui.system.reboot import RebootBusy, RebootJob
from openwrtgui.system.sampler import SystemSampler
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import BytesStream, ReplayTransport


async def _sim(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.system is not None
    return t


async def _job_end(ctx: AppContext) -> RebootJob:
    for _ in range(200):
        job = ctx.system.reboot_job("ap2")
        if job is not None and job.phase not in ("armed", "waiting"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError("still rebooting")


async def test_two_backups_in_one_second_is_a_422(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 11, 10, 15, 0, 0)
    monkeypatch.setattr(ctx.system, "_clock", lambda: fixed)
    folder = backup_dir(ctx.data.root, "ap2")
    folder.mkdir(parents=True, exist_ok=True)
    other = folder / (backup_name("ap2", fixed) + ".part")
    other.write_bytes(b"\x1f\x8b")  # another backup of this second is still streaming
    with pytest.raises(ValueError, match="saved this second already"):
        await ctx.system.create_backup("ap2")
    assert other.exists()  # the other backup's part file is left alone


async def test_two_reboot_starts_at_once_arm_once(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simsystem, "REBOOT_S", 0.5)
    ctx.system.every_s = 0.2
    plan = await ctx.system.plan_reboot("ap2")
    results = await asyncio.gather(
        ctx.system.start_reboot("ap2", plan.digest),
        ctx.system.start_reboot("ap2", plan.digest),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == ["RebootBusy", "RebootJob"]
    assert [e.command for e in ctx.audit.query()].count(plan.lines[0]) == 1  # armed once
    assert isinstance(next(r for r in results if not isinstance(r, RebootJob)), RebootBusy)
    await _job_end(ctx)


async def test_a_failed_rc_local_read_is_named(ctx: AppContext) -> None:
    sim = (await _sim(ctx)).state.system  # type: ignore[union-attr]
    assert sim is not None
    real = sim.answer
    answers = {"err": "cat: can't open '/etc/rc.local': Permission denied\n"}

    def refusing(command: str) -> CommandResult | None:
        return CommandResult(command, "", answers["err"], 1) if command == s.RC_LOCAL else real(command)

    sim.answer = refusing  # type: ignore[method-assign]
    with pytest.raises(
        ValueError, match="rc.local does not read: cat: can't open '/etc/rc.local': Permission"
    ):
        await ctx.system.rc_local("ap2")
    answers["err"] = "cat: can't open '/etc/rc.local': No such file or directory\n"
    assert await ctx.system.rc_local("ap2") == ""  # no file: Apply creates it


async def test_backup_acl_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    threads: list[int] = []
    monkeypatch.setattr(backup_module, "restrict_to_user", lambda path: threads.append(threading.get_ident()))

    class Streaming:
        async def stream(self, command: str) -> BytesStream:
            return BytesStream(gzip.compress(b"archive"), 0)

    await backup_module.save_archive(Streaming(), tmp_path / "ap2-20261110-150000.tar.gz")  # type: ignore[arg-type]
    assert len(threads) == 2 and threading.get_ident() not in threads  # icacls blocks: never on the loop


async def test_sampler_idles_while_the_router_reboots(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sampler = SystemSampler("ap2", pool=ctx.pool, routers=ctx.routers, busy=lambda rid: f"{rid} is busy")
    assert await asyncio.wait_for(sampler.tick(), 1.0) == {"type": "system-idle", "reason": "ap2 is busy"}
    monkeypatch.setattr(simsystem, "REBOOT_S", 0.5)
    ctx.system.every_s = 0.2
    await ctx.system.start_reboot("ap2", (await ctx.system.plan_reboot("ap2")).digest)
    live = await asyncio.wait_for(ctx.system_live.sampler("ap2").tick(), 1.0)  # the hub knows the job
    assert live == {"type": "system-idle", "reason": "AP2 · office is rebooting"}
    await _job_end(ctx)


async def test_emptied_crontab_removes_the_file(ctx: AppContext) -> None:
    task = "*/30 * * * * logger owg-test\n"
    added = await ctx.system.apply_crontab("ap2", task, (await ctx.system.plan_crontab("ap2", task)).digest)
    assert added.verified
    plan = await ctx.system.plan_crontab("ap2", "")
    assert plan.lines == ("rm -f /etc/crontabs/root", "/etc/init.d/cron restart")
    result = await ctx.system.apply_crontab("ap2", "", plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert [c.name for c in result.checks] == ["removed"]
    t = await _sim(ctx)
    assert not (await t.run(s.CRONTAB)).ok  # no file, as AP2 was found
    with pytest.raises(ValueError, match="Nothing"):
        await ctx.system.plan_crontab("ap2", "")
