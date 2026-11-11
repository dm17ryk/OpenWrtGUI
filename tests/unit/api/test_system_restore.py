"""Restore a backup (plan Task 14, D11) in the simulator: refused before anything is sent when it is not
this router's or would lock the app out; otherwise uploaded, listed, restored, rebooted, and proven by a
fresh uptime and every file's sha256."""

from __future__ import annotations

import asyncio
import io
import tarfile
from datetime import datetime

import httpx
import pytest

from openwrtgui import simsystem
from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system import commands as s
from openwrtgui.system.reboot import RebootBusy, RebootJob
from openwrtgui.system.settings import SystemSettings
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simsystem, "REBOOT_S", 0.5)
    ctx.system.every_s = 0.2


async def wait_job(ctx: AppContext, timeout: float = 20.0) -> RebootJob:
    for _ in range(int(timeout / 0.1)):
        job = ctx.system.reboot_job("ap2")
        if job is not None and job.phase not in ("armed", "waiting"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"still running: {ctx.system.reboot_job('ap2')}")


async def _sim(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport)
    return t


async def _backup_then_rename(ctx: AppContext) -> str:
    """A backup of AP2 as it is (hostname OpenWrt), then the hostname changed on the router."""
    saved = await ctx.system.create_backup("ap2")
    change = SystemSettings(hostname="changed")
    await ctx.system.apply_settings("ap2", change, (await ctx.system.plan_settings("ap2", change)).digest)
    assert (await ctx.system.overview("ap2")).hostname == "changed"
    return saved.name


def _archive(files: dict[str, str]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return raw.getvalue()


async def test_restore_proven_by_the_files(ctx: AppContext) -> None:
    name = await _backup_then_rename(ctx)
    check = await ctx.system.check_restore("ap2", name)
    assert check.refusals == () and "/etc/config/system" in check.files
    plan = await ctx.system.plan_restore("ap2", name)
    assert plan.lines[0].startswith(f"{s.UPLOAD_RESTORE}  # stdin: {name} (")
    assert plan.lines[1:3] == (s.LIST_RESTORE, s.RESTORE)
    assert any("settings become the backup's" in w for w in plan.warnings)
    job = await ctx.system.start_restore("ap2", name, plan.digest)
    assert (job.kind, job.phase) == ("restore", "armed")
    done = await wait_job(ctx)
    assert (done.phase, done.error) == ("back", None), done
    assert done.detail is not None and "every restored file matches" in done.detail
    assert (await ctx.system.overview("ap2")).hostname == "OpenWrt"  # the backup's
    for line in (e.command for e in ctx.audit.query()):
        assert "option hostname" not in line  # the archive's bytes are never logged


async def test_restore_refuses_another_routers_backup(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter(range(100))
    monkeypatch.setattr(
        ctx.system, "_clock", lambda: datetime(2026, 11, 10, 15, 0, next(ticks))
    )  # names per second
    moved = _archive({"etc/config/network": "config interface 'lan'\n\toption ipaddr '192.168.1.1'\n"})
    other = await ctx.system.import_backup("ap2", moved, "ap1.tar.gz")
    check = await ctx.system.check_restore("ap2", other.name)
    assert check.refusals == (
        "this backup puts AP2 · office at 192.168.1.1; the app reaches it at 192.168.1.2",
    )
    locked = _archive({"etc/dropbear/authorized_keys": ""})
    lockout = await ctx.system.import_backup("ap2", locked, "no-keys.tar.gz")
    assert (await ctx.system.check_restore("ap2", lockout.name)).refusals == (
        "after the restore the app could not log in to AP2 · office",
    )
    t = await _sim(ctx)
    with pytest.raises(ValueError, match="puts AP2"):
        await ctx.system.plan_restore("ap2", other.name)
    with pytest.raises(ValueError, match="could not log in"):
        await ctx.system.start_restore("ap2", lockout.name, "0" * 16)
    assert s.UPLOAD_RESTORE not in t.uploads  # nothing was sent
    with pytest.raises(LookupError):
        await ctx.system.check_restore("ap2", "../x.tar.gz")


async def test_restore_upload_failure_leaves_nothing(ctx: AppContext) -> None:
    name = (await ctx.system.create_backup("ap2")).name
    t = await _sim(ctx)
    assert t.state is not None and t.state.access is not None
    real = t.state.access.answer

    def refusing(command: str) -> CommandResult | None:
        if command == s.LIST_RESTORE:
            return CommandResult(command, "", "tar: invalid tar magic\n", 1)
        return real(command)

    t.state.access.answer = refusing  # type: ignore[method-assign]
    plan = await ctx.system.plan_restore("ap2", name)
    with pytest.raises(ValueError, match="does not read the backup"):
        await ctx.system.start_restore("ap2", name, plan.digest)
    assert s.REMOVE_RESTORE in [e.command for e in ctx.audit.query()]
    assert ctx.system.reboot_job("ap2") is None


async def test_restore_while_a_reboot_runs(ctx: AppContext) -> None:
    name = (await ctx.system.create_backup("ap2")).name
    await ctx.system.start_reboot("ap2", (await ctx.system.plan_reboot("ap2")).digest)
    plan = await ctx.system.plan_restore("ap2", name)
    with pytest.raises(RebootBusy):
        await ctx.system.start_restore("ap2", name, plan.digest)
    await wait_job(ctx)


async def test_restore_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    name = (await ctx_guard_live.system.create_backup("ap2")).name  # a backup works during a run
    plan = await ctx_guard_live.system.plan_restore("ap2", name)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.start_restore("ap2", name, plan.digest)


async def test_restore_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    name = (await ctx.system.create_backup("ap2")).name
    base = "/api/routers/ap2/system/restore"
    check = await authed.post(f"{base}/check", json={"name": name})
    assert check.status_code == 200 and check.json()["refusals"] == []
    preview = await authed.post(f"{base}/preview", json={"name": name})
    assert preview.status_code == 200
    started = await authed.post(f"{base}/start", json={"name": name, "digest": preview.json()["digest"]})
    assert (started.status_code, started.json()["kind"]) == (200, "restore")
    assert (await authed.post(f"{base}/check", json={"name": "nope.tar.gz"})).status_code == 404
    await wait_job(ctx)


async def test_a_router_added_by_name_is_checked_at_its_address(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A router added by host name: the backup's interface addresses are compared with the address the name
    resolves to, not with the name (PR #48 review: every backup with a network config was refused)."""
    from openwrtgui.system import jobs

    saved = await ctx.system.create_backup("ap2")
    rec = ctx.routers.get("ap2")
    assert rec is not None
    ctx.routers.upsert(rec.model_copy(update={"host": "ap2.bench.lan"}))

    async def resolve(host: str) -> str:
        return {"ap2.bench.lan": "192.168.1.2"}.get(host, host)

    monkeypatch.setattr(jobs, "router_ipv4", resolve)
    check = await ctx.system.check_restore("ap2", saved.name)
    assert check.refusals == ()


async def test_router_ipv4() -> None:
    from openwrtgui.system.restore import router_ipv4

    assert await router_ipv4("192.168.1.2") == "192.168.1.2"
    assert await router_ipv4("localhost") == "127.0.0.1"
    assert await router_ipv4("no-such-host.invalid") == "no-such-host.invalid"  # the refusal then names it


async def test_an_import_in_the_same_second_leaves_the_other_alone(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two imports in one second get one name: the second is refused and the first one's part file stays
    (PR #48 review: it used to unlink the other import's file)."""
    from openwrtgui.system.backup import backup_dir, backup_name

    fixed = datetime(2026, 11, 11, 14, 0, 0)
    monkeypatch.setattr(ctx.system, "_clock", lambda: fixed)
    folder = backup_dir(ctx.data.root, "ap2")
    folder.mkdir(parents=True, exist_ok=True)
    other = folder / (backup_name("ap2", fixed, imported=True) + ".part")
    other.write_bytes(b"\x1f\x8b")  # another import of this second is still being written
    data = _archive({"etc/config/system": "config system\n"})
    with pytest.raises(ValueError, match="imported this second already"):
        await ctx.system.import_backup("ap2", data, "two.tar.gz")
    assert other.exists()
