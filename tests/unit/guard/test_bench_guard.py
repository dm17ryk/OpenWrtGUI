from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

import psutil
import pytest

from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo, scan_processes
from openwrtgui.store.settings import GuardWatchList

STARTED = datetime(2026, 11, 3, 21, 4)


def watch(**overrides: list[str]) -> GuardWatchList:
    base: dict[str, list[str]] = {
        "lock_files": [],
        "processes": [],
        "router_ssids": [],
        "router_processes": [],
    }
    base.update(overrides)
    return GuardWatchList(**base)


def no_processes() -> list[ProcessInfo]:
    return []


def test_lock_file_makes_guard_live(tmp_path: Path) -> None:
    lock = tmp_path / "voip.lock.own"
    lock.write_text("", encoding="utf-8")
    g = BenchGuard(watch(lock_files=[str(lock)]), lister=no_processes)
    state = g.check_local()
    assert state.live
    assert state.reasons[0].kind == "lock_file"
    assert state.reasons[0].text.startswith(f"Lock file {lock} present since ")


def test_missing_lock_file_is_clear(tmp_path: Path) -> None:
    g = BenchGuard(watch(lock_files=[str(tmp_path / "none.lock")]), lister=no_processes)
    assert not g.check_local().live


def test_process_match_names_the_run() -> None:
    g = BenchGuard(
        watch(processes=["dima_night.py"]),
        lister=lambda: [ProcessInfo(18244, ("C:\\py\\python.exe", "D:\\x\\dima_night.py"), STARTED)],
    )
    assert g.check_local().reasons[0].text == "dima_night.py started 21:04 (PID 18244)"


def test_process_glob_case_insensitive() -> None:
    reasons = scan_processes(
        ["txlab_*.py"], lister=lambda: [ProcessInfo(7, ("python", "D:\\w\\TXLAB_b4rx.py"), STARTED)]
    )
    assert [r.detail for r in reasons] == ["TXLAB_b4rx.py"]


def test_scan_skips_access_denied_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self, pid: int, cmdline: list[str] | None, deny: bool = False) -> None:
            self.pid, self._cmd, self._deny = pid, cmdline, deny

        def cmdline(self) -> list[str]:
            if self._deny:
                raise psutil.AccessDenied(self.pid)
            return self._cmd or []

        def create_time(self) -> float:
            return STARTED.timestamp()

    procs = [Proc(4, None, deny=True), Proc(18244, ["python", "dima_night.py"])]

    def fake_iter() -> Iterator[Proc]:
        return iter(procs)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    from openwrtgui.guard.bench_guard import psutil_lister

    found = scan_processes(["dima_night.py"], lister=psutil_lister)
    assert [r.detail for r in found] == ["dima_night.py"]


def test_router_ssid_sign_and_clear() -> None:
    g = BenchGuard(watch(router_ssids=["OpenWrtB"]), lister=no_processes)
    g.set_router_signs("ap2", ["OpenWrt", "OpenWrtB"])
    state = g.check_local()
    assert state.live and state.reasons[0].text == "SSID OpenWrtB on air on ap2"
    g.set_router_signs("ap2", [])
    assert not g.check_local().live


def test_forgetting_a_router_clears_its_signs() -> None:
    g = BenchGuard(watch(router_ssids=["OpenWrtB"]), lister=no_processes)
    g.set_router_signs("ap2", ["OpenWrtB"])
    g.set_router_signs("ap3", ["OpenWrt"])
    assert g.check_local().live
    g.forget_router("ap2")
    assert not g.check_local().live
    g.forget_router("ap9")  # unknown ids are fine


def test_require_clear_raises_guard_locked() -> None:
    g = BenchGuard(
        watch(processes=["dima_night.py"]),
        lister=lambda: [ProcessInfo(1, ("dima_night.py",), STARTED)],
    )
    g.check_local()
    with pytest.raises(GuardLocked) as exc:
        g.require_clear()
    assert exc.value.state.live


def test_update_watch_takes_effect() -> None:
    procs: Iterable[ProcessInfo] = [ProcessInfo(1, ("rh_soak.py",), STARTED)]
    g = BenchGuard(watch(), lister=lambda: procs)
    assert not g.check_local().live
    g.update_watch(watch(processes=["rh_soak.py"]))
    assert g.check_local().live
