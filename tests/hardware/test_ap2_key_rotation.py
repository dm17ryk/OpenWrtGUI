"""AP2 window, 1.1b Part 2 (D8, D9): the app key rotation on AP2, with a throwaway app key.

    uv run pytest -m hardware tests/hardware/test_ap2_key_rotation.py --router 192.168.1.2 --identity <key> \
        --known-hosts <file> --allow-writes --txctl-told -v

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. No password is
used: the window logs in with --identity, installs a throwaway app key made in a temporary folder, rotates it
with the app's own KeyRotation (an app whose data holds AP2 only), and in the end removes both throwaway
lines, so AP2's /etc/dropbear/authorized_keys is exactly as found. No other line of that file is ever changed.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.onboard.rotate import KEYS_READ, KeyRotation, remove_old_key_command
from openwrtgui.onboard.wizard import SshConnector, install_key_command
from openwrtgui.store.keys import AppKeyRing
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import AuthFailed, Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"


async def _keys_text(t: Transport) -> str:
    result = await t.run(KEYS_READ)
    assert result.ok, f"AP2's authorized_keys does not read (exit {result.exit_status})"
    return result.stdout


async def _login(host_keys: HostKeyStore, key: Path) -> None:
    t = await SshTransport.connect(AP2, 22, "root", host_keys=host_keys, key_paths=[key], prove=True)
    try:
        assert (await t.run("true")).ok
    finally:
        await t.close()


async def test_a_throwaway_app_key_rotates_on_ap2(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    snapshot = await _keys_text(ap2_rw)
    keep = next((line for line in snapshot.splitlines() if line.strip()), None)
    assert keep is not None, "AP2's authorized_keys must hold the window's own key"
    # `echo >>` would glue a line onto an unterminated last line, and the cleanup could not undo that
    assert snapshot.endswith("\n"), "AP2's authorized_keys has no final newline: stop, nothing was written"
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    ring = AppKeyRing(tmp_path / "keys", comment="owg-rotation-test@pc")
    old_line = ring.current.public_line
    old_private = tmp_path / "old_key"  # the throwaway old key, kept to prove it no longer logs in
    shutil.copyfile(ring.current.private_path, old_private)
    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))

    async def factory(rec: RouterRecord) -> Transport:
        return await SshTransport.connect(
            AP2, 22, "root", host_keys=host_keys, key_paths=router_key_paths(rec, ring.login_paths())
        )

    pool = ConnectionPool(factory)
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    try:
        assert (await ap2_rw.run(install_key_command(old_line))).ok  # as Add router does
        rotation = KeyRotation(
            keys=ring,
            routers=routers,
            pool=pool,
            connector=SshConnector(host_keys),
            guard=guard,
            audit=AuditLog(tmp_path / "audit"),
        )
        await rotation.start(rotation.preview().digest)
        job = await rotation.finished()
        print(f"\n{job}")
        assert job is not None and job.phase == "done", job
        await _login(host_keys, ring.current.private_path)
        with pytest.raises(AuthFailed):
            await _login(host_keys, old_private)
        after = await _keys_text(ap2_rw)
        assert after.splitlines() == [*snapshot.splitlines(), ring.current.public_line]
    finally:
        await pool.close_all()
        # every line this test may have put on AP2, whatever step failed (final review F5): the throwaway old
        # key, and the new key whether or not the rotation finished
        added = {old_line, ring.current.public_line, *([ring.next.public_line] if ring.next else [])}
        for line in sorted(added):
            await ap2_rw.run(remove_old_key_command(keep, line))
        assert await _keys_text(ap2_rw) == snapshot, "AP2's authorized_keys is not as found"
