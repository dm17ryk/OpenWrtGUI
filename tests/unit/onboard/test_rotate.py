"""App key rotation (v1.1b, spec 7.12, D8): moving one router to the new key in three audited steps."""

from __future__ import annotations

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
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import AppKeyRing
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import AuthFailed, Transport, Unreachable
from openwrtgui.transport.fake import SimState
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
AP2 = "192.168.1.2"
AK = "/etc/dropbear/authorized_keys"


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

        async def factory(rec: RouterRecord) -> Transport:
            if rec.id in self.offline:
                raise Unreachable(f"{rec.host}:22: No route to host")
            return await self.sim.connect(
                rec.host,
                rec.port,
                password=None,
                key_paths=router_key_paths(rec, self.keys.login_paths()),
                username=rec.username,
            )

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
    assert seen == [("The app key is being moved on AP2 · office", None, ["App key rotation"])]
    assert rotation.busy("ap2") is None and rotation.live() == []


def test_remove_old_key_command_checks_the_new_line_first() -> None:
    cmd = remove_old_key_command("ssh-ed25519 AAAAnew openwrtgui@pc", "ssh-ed25519 AAAAold openwrtgui@pc")
    assert cmd == (
        f"grep -qxF 'ssh-ed25519 AAAAnew openwrtgui@pc' {AK} && "
        f"grep -vxF 'ssh-ed25519 AAAAold openwrtgui@pc' {AK} > {AK}.owg && "
        f"chmod 600 {AK}.owg && mv -f {AK}.owg {AK}"
    )
