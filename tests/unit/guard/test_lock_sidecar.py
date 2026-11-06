"""dima_night's lock sidecars (`*.lock.own`): a live run holds byte 0; the file itself stays between runs."""

import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from openwrtgui.guard.bench_guard import BenchGuard, GuardState, ProcessInfo
from openwrtgui.store.settings import GuardWatchList

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="msvcrt locks exist on Windows only")

# What dima_night's OsLock.acquire does: open the sidecar, lock byte 0 without waiting, keep it for the run.
RUN = """
import msvcrt, sys
f = open(sys.argv[1], "a+b")
f.seek(0)
msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
print("held", flush=True)
sys.stdin.readline()
"""


def no_processes() -> list[ProcessInfo]:
    return []


def check(lock: Path) -> GuardState:
    watch = GuardWatchList(lock_files=[str(lock)], processes=[], router_ssids=[], router_processes=[])
    return BenchGuard(watch, lister=no_processes).check_local()


def settles(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@contextmanager
def held(path: Path) -> Iterator[None]:
    """Hold byte 0 through a second handle, as a run would (unlocking fails if the lock was lost)."""
    import msvcrt

    with path.open("a+b") as f:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        yield
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def opened_without_sharing(path: Path) -> Iterator[None]:
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]  # fmt: skip
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)  # GENERIC_READ, share none
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        yield
    finally:
        k32.CloseHandle(handle)


@pytest.fixture
def sidecar(tmp_path: Path) -> Path:
    own = tmp_path / "voip.lock.own"
    own.write_bytes(b"")
    return own


@windows_only
def test_held_sidecar_is_a_live_run(sidecar: Path) -> None:
    with held(sidecar):
        state = check(sidecar)
    assert state.live
    assert state.reasons[0].kind == "lock_held"
    assert state.reasons[0].text == f"Lock file {sidecar} held by a live run"


@windows_only
def test_sidecar_counts_until_the_run_that_holds_it_dies(sidecar: Path) -> None:
    run = subprocess.Popen(
        [sys.executable, "-c", RUN, str(sidecar)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert run.stdout is not None and run.stdout.readline().strip() == "held"
        assert check(sidecar).live
    finally:
        run.kill()
        run.wait(timeout=10)
    assert settles(lambda: not check(sidecar).live)
    assert sidecar.exists()


@windows_only
def test_leftover_sidecar_is_not_a_run(sidecar: Path) -> None:
    state = check(sidecar)
    assert not state.live
    assert state.reasons == ()


def test_missing_sidecar_is_not_a_run_and_is_not_created(tmp_path: Path) -> None:
    own = tmp_path / "voip.lock.own"
    assert not check(own).live
    assert not own.exists()


@windows_only
def test_check_gives_the_lock_back_and_leaves_the_file_alone(sidecar: Path) -> None:
    sidecar.write_bytes(b"12345")
    before = sidecar.stat()
    assert not check(sidecar).live
    with held(sidecar):  # a run can still take it: the check kept nothing
        assert check(sidecar).live
    after = sidecar.stat()
    assert sidecar.read_bytes() == b"12345"
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


@windows_only
def test_sidecar_that_cannot_be_opened_still_counts(sidecar: Path) -> None:
    with opened_without_sharing(sidecar):
        state = check(sidecar)
    assert state.live
    assert state.reasons[0].kind == "lock_file"


def test_sidecar_off_windows_counts_while_it_exists(sidecar: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    state = check(sidecar)
    assert state.live
    assert state.reasons[0].kind == "lock_file"
