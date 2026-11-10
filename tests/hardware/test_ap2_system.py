"""AP2 System window (v0.6b plan Task 18): the hostname and back, one scheduled task added and removed, a
sysntpd restart and a backup, applied the way the app applies them, on the real router.

uv run pytest -m hardware tests/hardware/test_ap2_system.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved and the txctl session was told of. None of it reloads Wi-Fi or the
network. The reboot test also needs --allow-reboot, the owner's own OK for it (AP2 is away about 90 s).
Each test leaves AP2 as it found it: `uci -X show system`, `/etc/rc.local`, `/etc/crontabs/root` (or its
absence), every service's enabled and running state, the live hostname, `/tmp/TZ` and the radio. A backup
holds AP2's secrets: it lives only in the test's own data folder and is removed before the test ends.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.paths import DataDir
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.system import commands as s
from openwrtgui.system.backup import backup_dir
from openwrtgui.system.parse import parse_board, parse_rc_list
from openwrtgui.system.service import SystemService
from openwrtgui.system.settings import SystemSettings
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import parse_uci_show

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"
TEST_HOSTNAME = "owg-test"
TEST_TASK = "*/30 * * * * logger owg-test\n"
SETTLE_S = 10  # procd's view of a restarted service settles within a few seconds


def _by_content(text: str) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    shown = parse_uci_show(text)
    return sorted(
        (
            shown[name],
            tuple(sorted((k.rsplit(".", 1)[1], v) for k, v in shown.items() if k.startswith(name + "."))),
        )
        for name in (k for k in shown if k.count(".") == 1)
    )


@dataclass(frozen=True)
class Found:
    system: list[tuple[str, tuple[tuple[str, str], ...]]]
    rc_local: tuple[int, str]
    crontabs_dir: int  # `test -d /etc/crontabs`
    crontab: tuple[int, str]  # exit 1: AP2 has no crontab
    services: tuple[tuple[str, bool, bool], ...]
    hostname: str | None
    tz: str
    radio: str


async def _found(t: Transport) -> Found:
    async def read(command: str) -> tuple[int, str]:
        result = await t.run(command)
        return result.exit_status, result.stdout

    rc = await t.run(s.RC_LIST)
    assert rc.ok, f"AP2's service list does not read: {rc.stderr.strip()}"
    board = parse_board((await t.run(s.BOARD)).stdout)
    return Found(
        system=_by_content((await t.run(s.UCI_SYSTEM)).stdout),
        rc_local=await read(s.RC_LOCAL),
        crontabs_dir=(await t.run("test -d /etc/crontabs")).exit_status,
        crontab=await read(s.CRONTAB),
        services=tuple((r.name, r.enabled, r.running) for r in parse_rc_list(rc.stdout)),
        hostname=board.hostname if board else None,
        tz=(await t.run(s.TZ_FILE)).stdout,
        radio=(await t.run("uci -q get wireless.radio0.disabled")).stdout.strip(),
    )


@pytest.fixture
async def system(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[SystemService]:
    found = await _found(ap2_rw)
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    identity: Path = request.config.getoption("--identity")

    async def connect() -> SshTransport:
        return await SshTransport.connect(AP2, 22, "root", host_keys=host_keys, key_paths=[identity])

    async def factory(rec: RouterRecord) -> Transport:
        return await connect()

    data = DataDir.at(tmp_path / "data")
    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(data.audit_dir)
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    service = SystemService(pool=pool, routers=routers, guard=guard, audit=audit, runner=runner, data=data)
    try:
        yield service
    finally:
        shutil.rmtree(backup_dir(data.root, "ap2"), ignore_errors=True)  # AP2's secrets never stay here
        assert not backup_dir(data.root, "ap2").exists(), "a backup of AP2 was not removed"
        await pool.close_all()
        t = await connect()
        try:
            if found.crontab[0] != 0 and (await t.run(s.CRONTAB)).ok:
                # the app writes an empty crontab where AP2 had none: put the absence back (cron then idles)
                assert (await t.run("rm -f /etc/crontabs/root")).ok, "the crontab's absence was not put back"
                await t.run(s.init("cron", "restart"))  # its exit is not the proof: rc list below is
            now = await _found(t)
            for _ in range(SETTLE_S):
                if now == found:
                    break
                await asyncio.sleep(1.0)
                now = await _found(t)
            assert now == found, f"AP2 is not as found: {now} != {found}"
        finally:
            await t.close()


async def test_hostname_and_back(system: SystemService) -> None:
    found = (await system.settings("ap2")).hostname
    assert found and found != TEST_HOSTNAME
    for name in (TEST_HOSTNAME, found):
        req = SystemSettings(hostname=name)
        plan = await system.plan_settings("ap2", req)
        assert any(line.endswith(f".hostname='{name}'") for line in plan.lines), plan.lines
        assert "/etc/init.d/system reload" in plan.lines, plan.lines
        started = time.monotonic()
        result = await system.apply_settings("ap2", req, plan.digest)
        print(f"\nhostname {name}: {time.monotonic() - started:.1f} s, {result.checks}")
        assert (result.applied, result.verified) == (True, True), result
        assert {c.name: c.detail for c in result.checks}["hostname"] == name


async def test_a_scheduled_task_added_and_removed(system: SystemService) -> None:
    before = await system.crontab("ap2")
    assert TEST_TASK not in before.text
    for text in (before.text + TEST_TASK, before.text):
        plan = await system.plan_crontab("ap2", text)
        assert plan.lines[0].endswith("cat > /etc/crontabs/root <<'OWG'"), plan.lines
        started = time.monotonic()
        result = await system.apply_crontab("ap2", text, plan.digest)
        print(f"\ncrontab {len(text)} bytes: {time.monotonic() - started:.1f} s, {result.checks}")
        assert (result.applied, result.verified) == (True, True), result
    after = await system.crontab("ap2")
    assert not after.tasks and after.text.strip() == before.text.strip()


async def test_sysntpd_restart(system: SystemService) -> None:
    plan = await system.plan_service("ap2", "sysntpd", "restart")
    assert plan.lines == ("/etc/init.d/sysntpd restart",) and plan.warnings == ()
    started = time.monotonic()
    result = await system.apply_service("ap2", "sysntpd", "restart", plan.digest)
    print(f"\nsysntpd restart: {time.monotonic() - started:.1f} s, {result.checks}")
    assert (result.applied, result.verified) == (True, True), result
    assert result.checks[0].detail == "running"


async def test_a_backup_is_saved(system: SystemService) -> None:
    started = time.monotonic()
    saved = await system.create_backup("ap2")
    print(f"\nbackup: {saved.size} bytes in {time.monotonic() - started:.1f} s")  # the size, never the file
    assert saved.size > 0
    assert [b.name for b in await system.backups("ap2")] == [saved.name]
    path = system.backup_path("ap2", saved.name)
    assert path.read_bytes()[:2] == b"\x1f\x8b"  # gzip
    path.unlink()
    assert await system.backups("ap2") == []


async def test_reboot_and_back(system: SystemService, request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--allow-reboot"):
        pytest.skip("rebooting AP2 needs the owner's own OK for it: --allow-reboot")
    plan = await system.plan_reboot("ap2")
    started = time.monotonic()
    await system.start_reboot("ap2", plan.digest)
    for _ in range(int(system.reboot_limit_s) + 60):  # the job ends by itself within the limit
        if not system.rebooting("ap2"):
            break
        await asyncio.sleep(1.0)
    job = system.reboot_job("ap2")
    print(f"\nreboot: {time.monotonic() - started:.0f} s, {job}")
    assert job is not None and job.phase == "back", job
