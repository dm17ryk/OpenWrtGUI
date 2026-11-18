"""App key rotation (v1.1b, spec 7.12, D8): moving one router to the new key in three audited steps."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.onboard.rotate import (
    KeyRotation,
    MoveFailed,
    RotationBusy,
    RotationJob,
    move_router,
    remove_old_key_command,
)
from openwrtgui.onboard.wizard import install_key_command
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import AppKeyRing
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import AuthFailed, CommandResult, Transport, Unreachable
from openwrtgui.transport.fake import SimState
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
AP2 = "192.168.1.2"
AK = "/etc/dropbear/authorized_keys"


class Dropping:
    """A pooled connection that is lost when it runs the bench's `drop_on` command."""

    def __init__(self, inner: Transport, bench: Bench) -> None:
        self._inner, self._bench = inner, bench

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if self._bench.drop_on is not None and command.startswith(self._bench.drop_on):
            self._bench.drop_on = None
            raise Unreachable("192.168.1.2:22: connection lost")
        return await self._inner.run(command, timeout=timeout)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class Bench:
    """A simulated bench: the app's key ring, its pool, Bench Guard and the audit log."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.sim = SimConnector(SIM_DIR)
        self.routers = RouterStore(tmp_path / "routers.json")
        seed_routers(SIM_DIR, self.routers)
        self.keys = AppKeyRing(tmp_path / "keys", comment="openwrtgui@TEST")
        self.procs: list[ProcessInfo] = []
        self.guard = BenchGuard(
            GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: self.procs
        )
        self.guard.check_local()
        self.audit = AuditLog(tmp_path / "audit")
        self.offline: set[str] = set()  # routers that do not answer
        self.connects = 0  # pooled connections made
        self.drop_on: str | None = None  # a command whose run loses the connection

        async def factory(rec: RouterRecord) -> Transport:
            if rec.id in self.offline:
                raise Unreachable(f"{rec.host}:22: No route to host")
            self.connects += 1
            t = await self.sim.connect(
                rec.host,
                rec.port,
                password=None,
                key_paths=router_key_paths(rec, self.keys.login_paths()),
                username=rec.username,
            )
            return Dropping(t, self)

        self.pool = ConnectionPool(factory)

    def state(self) -> SimState:
        return self.sim.state(AP2)

    def ap2(self) -> RouterRecord:
        rec = self.routers.get("ap2")
        assert rec is not None
        return rec

    def go_live(self) -> None:
        self.procs = [ProcessInfo(18244, ("dima_night.py",), datetime(2026, 11, 18, 21, 4))]
        self.guard.check_local()

    def audit_text(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in (self.tmp_path / "audit").glob("*.jsonl"))


@pytest.fixture
def bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bench:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    return Bench(tmp_path)


class RefusesTheNewKey:
    """The router's dropbear would not take the new key (the proof login fails)."""

    def __init__(self, inner: SimConnector, refused: Path) -> None:
        self._inner, self._refused = inner, refused

    async def connect(self, host: str, port: int, *, key_paths: Sequence[Path], **kw: object) -> Transport:
        if list(key_paths) == [self._refused]:
            raise AuthFailed(f"{host} refused the key")
        return await self._inner.connect(host, port, key_paths=key_paths, **kw)  # type: ignore[arg-type]


async def _seeded(bench: Bench) -> None:
    """The app logged in to AP2 once with its current key, as after Add router."""
    await bench.pool.get(bench.ap2())
    assert bench.keys.current.public_line in bench.state().authorized_keys


async def test_a_router_moves_in_three_audited_steps(bench: Bench) -> None:
    await _seeded(bench)
    old = bench.keys.current.public_line
    nxt = bench.keys.begin()
    steps: list[str] = []
    await move_router(
        bench.ap2(),
        keys=bench.keys,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        on_step=steps.append,
    )
    assert steps == ["adding", "proving", "removing"]
    assert nxt.public_line in bench.state().authorized_keys and old not in bench.state().authorized_keys
    assert bench.keys.moved() == frozenset({"ap2"})
    audit = bench.audit_text()
    assert "grep -qxF" in audit and "grep -vxF" in audit and "check authorized_keys" in audit
    assert "1 old line(s) removed" in audit


async def test_every_other_line_is_kept_byte_for_byte(bench: Bench) -> None:
    """Review Focus 3: a CRLF line, a comment, an options-prefixed copy of the old key, the old line twice."""
    await _seeded(bench)
    old = bench.keys.current.public_line
    others = [
        "# kept: the lab's keys",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIother bench@lab\r",
        f"no-pty {old}",
    ]
    bench.state().authorized_keys[:] = [*others, old, old]
    nxt = bench.keys.begin()
    await move_router(
        bench.ap2(),
        keys=bench.keys,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        on_step=lambda step: None,
    )
    assert bench.state().authorized_keys == [*others, nxt.public_line]
    assert "2 old line(s) removed" in bench.audit_text()


async def test_an_old_key_kept_by_another_line_is_named(bench: Bench) -> None:
    """Final review F3: only exact old lines go, but a copy of the old key in another form is reported."""
    await _seeded(bench)
    old = bench.keys.current.public_line
    bench.state().authorized_keys[:] = [f"no-pty {old}", old]
    bench.keys.begin()
    warning = await move_router(
        bench.ap2(),
        keys=bench.keys,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        on_step=lambda step: None,
    )
    assert warning == "the old key is still accepted by 1 other line: remove it on System › Access"
    assert bench.keys.moved() == frozenset({"ap2"})
    assert "old key still accepted by 1 other line" in bench.audit_text()


async def test_a_router_that_refuses_the_new_key_keeps_the_old_line(bench: Bench) -> None:
    await _seeded(bench)
    old = bench.keys.current.public_line
    nxt = bench.keys.begin()
    with pytest.raises(MoveFailed, match=r"^AP2 · office did not accept the new key: the old key stays$"):
        await move_router(
            bench.ap2(),
            keys=bench.keys,
            pool=bench.pool,
            connector=RefusesTheNewKey(bench.sim, nxt.private_path),  # type: ignore[arg-type]
            guard=bench.guard,
            audit=bench.audit,
            on_step=lambda step: None,
        )
    assert old in bench.state().authorized_keys
    assert bench.keys.moved() == frozenset()


async def test_a_router_that_does_not_answer_stays_on_the_old_key(bench: Bench) -> None:
    await _seeded(bench)
    bench.keys.begin()
    await bench.pool.drop("ap2")
    bench.offline.add("ap2")
    with pytest.raises(MoveFailed, match=r"^AP2 · office did not answer: it stays on the old key$"):
        await move_router(
            bench.ap2(),
            keys=bench.keys,
            pool=bench.pool,
            connector=bench.sim,
            guard=bench.guard,
            audit=bench.audit,
            on_step=lambda step: None,
        )
    assert bench.keys.moved() == frozenset()


async def test_the_remove_command_refuses_without_the_new_line(bench: Bench) -> None:
    await _seeded(bench)
    old = bench.keys.current.public_line
    nxt = bench.keys.begin()
    t = await bench.pool.get(bench.ap2())
    before = list(bench.state().authorized_keys)
    result = await t.run(remove_old_key_command(nxt.public_line, old))
    assert result.exit_status == 1
    assert bench.state().authorized_keys == before


async def test_a_harness_run_stops_the_move(bench: Bench) -> None:
    await _seeded(bench)
    old = bench.keys.current.public_line
    nxt = bench.keys.begin()

    def step(name: str) -> None:
        if name == "proving":
            bench.go_live()  # a harness run starts after the new key was added

    with pytest.raises(GuardLocked):
        await move_router(
            bench.ap2(),
            keys=bench.keys,
            pool=bench.pool,
            connector=bench.sim,
            guard=bench.guard,
            audit=bench.audit,
            on_step=step,
        )
    assert old in bench.state().authorized_keys and nxt.public_line in bench.state().authorized_keys
    assert bench.keys.moved() == frozenset()


# ---------------------------------------------------------------- the rotation job (Task 6)

TARGETS = ("ap1", "ap2")  # the seeded routers on the app's key; ap3 has none installed


def _rotation(bench: Bench, busy: Sequence[Callable[[str], str | None]] = ()) -> KeyRotation:
    return KeyRotation(
        keys=bench.keys,
        routers=bench.routers,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        busy=busy,
    )


def _rows(job: RotationJob | None) -> dict[str, tuple[str, str | None]]:
    assert job is not None
    return {r.router_id: (r.state, r.detail) for r in job.routers}


async def _run(rotation: KeyRotation) -> RotationJob:
    await rotation.start(rotation.preview().digest)
    job = await rotation.finished()
    assert job is not None
    return job


async def test_three_routers_move_and_the_key_is_replaced(bench: Bench) -> None:
    old_fingerprint = bench.keys.current.fingerprint
    job = await _run(_rotation(bench))
    assert job.phase == "done" and job.old_fingerprint == old_fingerprint
    assert _rows(job) == {rid: ("moved", None) for rid in TARGETS}
    assert bench.keys.next is None and bench.keys.current.fingerprint == job.new_fingerprint
    assert not (bench.tmp_path / "keys" / "id_ed25519.next").exists()
    for rid in TARGETS:  # every router still logs in, now with the new key only
        await bench.pool.drop(rid)
        rec = bench.routers.get(rid)
        assert rec is not None and (await (await bench.pool.get(rec)).run("true")).ok
    assert "replace the app key on this PC" in bench.audit_text()


async def test_a_router_that_is_off_stays_on_the_old_key(bench: Bench) -> None:
    """Review Focus 1."""
    bench.offline.add("ap1")
    rotation = _rotation(bench)
    job = await _run(rotation)
    assert job.phase == "pending"
    assert _rows(job)["ap1"] == ("failed", "AP1 · bench did not answer: it stays on the old key")
    assert _rows(job)["ap2"] == ("moved", None)
    assert (bench.tmp_path / "keys" / "id_ed25519.next").exists() and bench.keys.next is not None
    bench.offline.clear()
    await rotation.retry("ap1")
    job = await rotation.finished()
    assert job is not None and job.phase == "done" and bench.keys.next is None


async def test_a_rotation_continues_after_a_restart(bench: Bench) -> None:
    """Review Focus 2: the app stops with one router moved; a new ring and job on the same folder go on."""
    bench.offline.add("ap1")
    first = await _run(_rotation(bench))
    assert first.phase == "pending" and _rows(first)["ap2"] == ("moved", None)
    bench.keys = AppKeyRing(bench.tmp_path / "keys")  # the app restarted
    bench.offline.clear()
    rotation = _rotation(bench)
    found = rotation.job()
    assert found is not None and found.phase == "pending" and found.started_at is None
    assert _rows(found) == {"ap1": ("waiting", None), "ap2": ("moved", None)}
    assert rotation.preview().lines[0] == "Continue: 1 router(s) still on the old key."
    job = await _run(rotation)
    assert job.phase == "done" and bench.keys.next is None


async def test_start_twice_gives_409(bench: Bench) -> None:
    rotation = _rotation(bench)
    digest = rotation.preview().digest
    await rotation.start(digest)
    with pytest.raises(RotationBusy, match="App key rotation already runs"):
        await rotation.start(digest)
    await rotation.finished()


async def test_a_moved_router_given_the_old_key_again_moves_again(bench: Bench) -> None:
    """Final review F1: AP2 moved, then was reflashed and added again with the old key while AP1 waited. The
    final check before the old key is deleted finds it, so AP2 moves again instead of being locked out."""
    bench.offline.add("ap1")
    rotation = _rotation(bench)
    first = await _run(rotation)
    assert _rows(first)["ap2"] == ("moved", None)
    old = bench.keys.current.public_line
    bench.state().authorized_keys[:] = [
        old
    ]  # reflashed without settings, then Add router installed the old key
    await bench.pool.drop("ap2")
    bench.offline.clear()
    await rotation.retry("ap1")
    job = await rotation.finished()
    assert job is not None and job.phase == "pending" and bench.keys.next is not None
    assert _rows(job)["ap2"] == (
        "failed",
        "AP2 · office no longer accepts the new key: it moves again on Retry",
    )
    assert bench.keys.moved() == frozenset({"ap1"})
    await rotation.retry("ap2")
    job = await rotation.finished()
    assert job is not None and job.phase == "done"


async def test_an_open_add_router_holds_the_finish(bench: Bench) -> None:
    """Final review F1: a wizard that installed the old key and is not finished keeps the old key alive."""
    holding = "Add router has installed the app key on 192.168.1.4 and is not finished"
    rotation = KeyRotation(
        keys=bench.keys,
        routers=bench.routers,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        hold=lambda: holding,
    )
    job = await _run(rotation)
    assert (job.phase, job.detail) == ("pending", holding) and bench.keys.next is not None


async def test_a_failed_replace_on_this_pc_ends_the_job(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review F4: the job never stays "running" when replacing the key on this PC fails."""

    def fails() -> object:
        raise OSError("The process cannot access the file")

    monkeypatch.setattr(bench.keys, "finish", fails)
    job = await _run(_rotation(bench))
    assert job.phase == "pending"
    assert job.detail == "Replacing the key on this PC failed: The process cannot access the file"


async def test_a_router_written_during_the_final_check_moves_again(bench: Bench) -> None:
    """PR #89 review (P1): the final check holds every router's write lock until the key is replaced, so a
    restore of an old-key-only backup on AP2 cannot land between AP2's proof and the replacement."""
    bench.offline.add("ap1")
    rotation = _rotation(bench)
    await _run(rotation)
    bench.offline.clear()
    old = bench.keys.current.public_line
    restore = bench.pool.write_lock("ap2")
    await restore.acquire()  # a restore holds AP2 while the rotation finishes
    try:
        await rotation.retry("ap1")
        for _ in range(200):  # AP1 moves, then the final check waits for AP2
            if _rows(rotation.job()).get("ap1") == ("moved", None):
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert rotation.busy("ap2") == "The app key is being replaced on this PC"
        bench.state().authorized_keys[:] = [old]  # the restore puts back a backup with only the old key
    finally:
        restore.release()
    job = await rotation.finished()
    assert job is not None and job.phase == "pending" and bench.keys.next is not None
    assert _rows(job)["ap2"] == (
        "failed",
        "AP2 · office no longer accepts the new key: it moves again on Retry",
    )


async def test_add_router_starting_during_the_final_check_holds_the_finish(bench: Bench) -> None:
    """PR #89 review (P1): the hold is asked again right before the replacement, not only before proofs."""
    asked: list[str | None] = [
        None,
        "Add router has installed the app key on 192.168.1.4 and is not finished",
    ]

    def hold() -> str | None:
        return asked.pop(0) if len(asked) > 1 else asked[0]

    rotation = KeyRotation(
        keys=bench.keys,
        routers=bench.routers,
        pool=bench.pool,
        connector=bench.sim,
        guard=bench.guard,
        audit=bench.audit,
        hold=hold,
    )
    job = await _run(rotation)
    assert (job.phase, job.detail) == (
        "pending",
        "Add router has installed the app key on 192.168.1.4 and is not finished",
    )
    assert bench.keys.next is not None


async def test_a_lost_connection_is_dropped_so_retry_reconnects(bench: Bench) -> None:
    """PR #89 review (P2): a connection lost mid-move is not handed to the Retry again."""
    await _seeded(bench)
    bench.keys.begin()
    bench.drop_on = "grep -qxF"  # lost while removing the old line
    with pytest.raises(MoveFailed, match="did not answer"):
        await move_router(
            bench.ap2(),
            keys=bench.keys,
            pool=bench.pool,
            connector=bench.sim,
            guard=bench.guard,
            audit=bench.audit,
            on_step=lambda step: None,
        )
    before = bench.connects
    await bench.pool.get(bench.ap2())
    assert bench.connects == before + 1  # a new connection, not the lost one


SH = shutil.which("sh")


def _local(command: str, folder: Path) -> str:
    return command.replace("/etc/dropbear", folder.as_posix())


@pytest.mark.skipif(SH is None, reason="needs a POSIX sh with grep and tail")
def test_installing_a_key_keeps_a_last_line_without_newline(tmp_path: Path) -> None:
    """PR #89 review (P1): `echo >>` on a file whose last line has no newline glued the key onto it."""
    ak = tmp_path / "authorized_keys"
    ak.write_bytes(b"ssh-ed25519 AAAAold openwrtgui@pc")  # no final newline
    cmd = _local(install_key_command("ssh-ed25519 AAAAnew openwrtgui@pc"), tmp_path)
    assert subprocess.run([SH, "-c", cmd], check=False).returncode == 0  # noqa: S603
    assert ak.read_bytes() == b"ssh-ed25519 AAAAold openwrtgui@pc\nssh-ed25519 AAAAnew openwrtgui@pc\n"
    assert subprocess.run([SH, "-c", cmd], check=False).returncode == 0  # noqa: S603 - a second install adds nothing
    assert ak.read_bytes().count(b"AAAAnew") == 1


@pytest.mark.skipif(SH is None, reason="needs a POSIX sh with grep and tail")
def test_the_remove_command_on_a_real_shell(tmp_path: Path) -> None:
    """Review Focus 3 on real grep: only exact old lines go; CRLF and options copies stay byte for byte."""
    old, new = "ssh-ed25519 AAAAold openwrtgui@pc", "ssh-ed25519 AAAAnew openwrtgui@pc"
    ak = tmp_path / "authorized_keys"
    # Git for Windows' grep writes CRLF lines back as LF; the router's BusyBox grep keeps the bytes (Linux CI)
    other = b"ssh-ed25519 AAAAother bench@lab" + (b"" if sys.platform == "win32" else b"\r")
    kept = [b"# kept", other, f"no-pty {old}".encode()]
    ak.write_bytes(b"\n".join([*kept, old.encode(), old.encode(), new.encode()]) + b"\n")
    cmd = _local(remove_old_key_command(new, old), tmp_path)
    assert subprocess.run([SH, "-c", cmd], check=False).returncode == 0  # noqa: S603
    assert ak.read_bytes() == b"\n".join([*kept, new.encode()]) + b"\n"
    assert not (tmp_path / "authorized_keys.owg").exists()
    ak.write_bytes(f"{old}\n".encode())  # no new line: the command refuses and writes nothing
    assert subprocess.run([SH, "-c", cmd], check=False).returncode != 0  # noqa: S603
    assert ak.read_bytes() == f"{old}\n".encode() and not (tmp_path / "authorized_keys.owg").exists()


async def test_a_changed_router_list_needs_a_new_preview(bench: Bench) -> None:
    rotation = _rotation(bench)
    digest = rotation.preview().digest
    bench.routers.remove("ap1")
    with pytest.raises(PreviewChanged):
        await rotation.start(digest)
    assert bench.keys.next is None


async def test_refused_during_a_harness_run(bench: Bench) -> None:
    rotation = _rotation(bench)
    digest = rotation.preview().digest
    bench.go_live()
    with pytest.raises(GuardLocked):
        await rotation.start(digest)
    assert bench.keys.next is None


async def test_a_harness_run_during_the_job_leaves_the_rest_waiting(bench: Bench) -> None:
    def starts_a_run(router_id: str) -> str | None:
        if router_id == "ap2":
            bench.go_live()  # a harness run starts while AP1 has just moved
        return None

    job = await _run(_rotation(bench, busy=[starts_a_run]))
    assert (job.phase, job.detail) == ("pending", "A harness run started: the rest stay on the old key")
    assert _rows(job) == {"ap1": ("moved", None), "ap2": ("waiting", None)}  # seen before its first step
    assert bench.keys.next is not None  # the old key stays on this PC


async def test_a_router_busy_with_a_flash_is_failed_with_that_reason(bench: Bench) -> None:
    def flashing(router_id: str) -> str | None:
        return "A flash runs on AP1 · bench" if router_id == "ap1" else None

    job = await _run(_rotation(bench, busy=[flashing]))
    assert job.phase == "pending" and _rows(job)["ap1"] == ("failed", "A flash runs on AP1 · bench")
    assert _rows(job)["ap2"] == ("moved", None)


async def test_skipped_routers_are_named_in_the_preview(bench: Bench, tmp_path: Path) -> None:
    ap1 = bench.routers.get("ap1")
    assert ap1 is not None
    bench.routers.upsert(ap1.model_copy(update={"key_path": str(tmp_path / "id_rsa")}))
    lines = _rotation(bench).preview().lines
    assert lines[0] == (
        "Make a new app key, then for each router: add the new key, log in with it, "
        "remove the old key's line. Other lines in authorized_keys are not changed."
    )
    assert "AP2 · office (192.168.1.2): moves to the new key" in lines
    assert "AP1 · bench: skipped, it logs in with your own key" in lines
    assert "AP3 · QA stands: skipped, the app key is not installed on it" in lines


async def test_busy_and_live_name_the_move(bench: Bench) -> None:
    seen: list[tuple[str | None, str | None, list[str]]] = []
    holder: list[KeyRotation] = []

    class Watching:
        """Looks at the job while AP2's proof login runs."""

        async def connect(self, host: str, port: int, **kw: object) -> Transport:
            if host == AP2:
                seen.append((holder[0].busy("ap2"), holder[0].busy("ap1"), holder[0].live()))
            return await bench.sim.connect(host, port, **kw)  # type: ignore[arg-type]

    rotation = KeyRotation(
        keys=bench.keys,
        routers=bench.routers,
        pool=bench.pool,
        connector=Watching(),  # type: ignore[arg-type]
        guard=bench.guard,
        audit=bench.audit,
        busy=(),
    )
    holder.append(rotation)
    await _run(rotation)
    assert seen == [
        ("The app key is being moved on AP2 · office", None, ["App key rotation"]),  # AP2's proof login
        # the final check before the old key is deleted (F1): every router is held (PR #89 review)
        (
            "The app key is being replaced on this PC",
            "The app key is being replaced on this PC",
            ["App key rotation"],
        ),
    ]
    assert rotation.busy("ap2") is None and rotation.live() == []


def test_remove_old_key_command_checks_the_new_line_first() -> None:
    """Final review F2: the temp file is checked (the new line and every kept line in it) before the rename,
    and removed when anything fails, so a full overlay never installs a cut-off authorized_keys."""
    new, old = "'ssh-ed25519 AAAAnew openwrtgui@pc'", "'ssh-ed25519 AAAAold openwrtgui@pc'"
    cmd = remove_old_key_command("ssh-ed25519 AAAAnew openwrtgui@pc", "ssh-ed25519 AAAAold openwrtgui@pc")
    tmp = f"{AK}.owg"
    assert cmd == (
        f"grep -qxF {new} {AK} && {{ grep -vxF {old} {AK} > {tmp} && grep -qxF {new} {tmp} && "
        f'[ "$(grep -cvxF {old} {AK})" = "$(grep -c \'\' {tmp})" ] && chmod 600 {tmp} && mv -f {tmp} {AK} '
        f"|| {{ rm -f {tmp}; false; }}; }}"
    )
