from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from openwrtgui import paths
from openwrtgui.rf.recorder import COLUMNS, CsvRecorder
from openwrtgui.rf.sample import RadioSample, RfSample, StationSample
from openwrtgui.rf.sampler import RfSampler
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport, Unreachable
from openwrtgui.transport.pool import ConnectionPool

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 9, 0, 0)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _sampler(tmp_path: Path, wrap: type | None = None, router: str = "ap1") -> tuple[RfSampler, list[str]]:
    connector = SimConnector(SIM_DIR)
    routers = RouterStore(tmp_path / "routers.json")
    seed_routers(SIM_DIR, routers)
    calls: list[str] = []

    async def factory(rec: RouterRecord) -> Transport:
        t = await connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])
        return wrap(t, calls) if wrap else _Count(t, calls)

    async def no_sleep(_: float) -> None:
        await asyncio.sleep(0)

    sampler = RfSampler(
        router, "radio0", pool=ConnectionPool(factory), routers=routers, clock=Clock(), sleep=no_sleep
    )
    return sampler, calls


class _Count:
    def __init__(self, inner: Transport, calls: list[str]) -> None:
        self._inner, self._calls = inner, calls

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self._calls.append(command)
        return await self._inner.run(command, timeout=timeout)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class _FailsOnce(_Count):
    failed = False

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if command.startswith("echo ===STA") and not _FailsOnce.failed:
            _FailsOnce.failed = True
            raise Unreachable("192.168.1.1:22: connection lost")
        return await super().run(command, timeout=timeout)


async def test_tick_reads_the_radio_and_the_station(tmp_path: Path) -> None:
    sampler, _ = _sampler(tmp_path)
    await sampler.tick()
    msg = await sampler.tick()
    assert msg["type"] == "rf"
    sample: RfSample = msg["sample"]
    assert sample.radio_sample.channel == 1 and sample.radio_sample.busy_pct == 23.0
    [sta] = sample.stations
    assert sta.mac == "f4:12:fa:f3:57:68" and sta.name == "panel" and sta.tx is not None and sta.tx.mcs == 7


async def test_parked_radio_sends_idle(tmp_path: Path) -> None:
    sampler, _ = _sampler(tmp_path, router="ap2")
    assert await sampler.tick() == {"type": "rf-idle", "reason": "radio0 is parked"}


async def test_router_unreachable_sends_idle_and_keeps_running(tmp_path: Path) -> None:
    _FailsOnce.failed = False
    sampler, _ = _sampler(tmp_path, wrap=_FailsOnce)
    first = await sampler.tick()
    assert first == {"type": "rf-idle", "reason": "192.168.1.1:22: connection lost"}
    assert (await sampler.tick())["type"] == "rf"


class _NoHints(_Count):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if "getHostHints" in command:
            self._calls.append(command)
            return CommandResult(command, "", "Command failed: Request timed out", 7)
        return await super().run(command, timeout=timeout)


async def test_a_failed_name_lookup_still_samples_and_is_not_retried_every_second(tmp_path: Path) -> None:
    sampler, calls = _sampler(tmp_path, wrap=_NoHints)
    first, second = await sampler.tick(), await sampler.tick()
    assert first["type"] == "rf" and second["type"] == "rf"
    assert second["sample"].stations[0].name is None
    assert sum("getHostHints" in c for c in calls) == 1


async def test_an_unexpected_error_is_reported_and_sampling_goes_on(tmp_path: Path) -> None:
    sampler, _ = _sampler(tmp_path)
    real_tick = sampler.tick
    failed = False

    async def tick_once_broken() -> dict[str, object]:
        nonlocal failed
        if not failed:
            failed = True
            raise ValueError("odd station dump line")
        return await real_tick()  # type: ignore[return-value]

    sampler.tick = tick_once_broken  # type: ignore[method-assign]
    queue = sampler.subscribe()
    first = await asyncio.wait_for(queue.get(), 5)
    assert first == {"type": "rf-idle", "reason": "RF sampling failed: odd station dump line"}
    assert (await asyncio.wait_for(queue.get(), 5))["type"] == "rf"
    sampler.unsubscribe(queue)


async def test_sampler_runs_only_while_subscribed(tmp_path: Path) -> None:
    sampler, calls = _sampler(tmp_path)
    await asyncio.sleep(0)
    assert not any(c.startswith("echo ===STA") for c in calls)
    queue = sampler.subscribe()
    first = await asyncio.wait_for(queue.get(), 5)
    assert first["type"] == "rf"
    sampler.unsubscribe(queue)
    await asyncio.sleep(0.05)
    count = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == count and not sampler.running


def _sample(at: datetime, stations: tuple[StationSample, ...]) -> RfSample:
    radio = RadioSample(6, 2437, 20, 20.0, 23.0, None, 3.0)
    return RfSample(at, "ap1", "radio0", "phy0-ap0", radio, stations, ())


def _station(mac: str) -> StationSample:
    return StationSample(
        mac, "panel", -52, -53, (-54, -55), None, None, 10.0, 8.0, 12.0, 9.0, 4.1, 0.2, 0, 40, 38.0, None
    )


def test_csv_columns_stable_when_station_leaves(tmp_path: Path) -> None:
    path = tmp_path / "rf.csv"
    rec = CsvRecorder(path)
    t = datetime(2026, 11, 5, 9, 0, 0)
    rec.write(_sample(t, (_station("f4:12:fa:f3:57:68"),)))
    rec.write(_sample(t + timedelta(seconds=1), ()))
    rec.close()
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert tuple(rows[0]) == COLUMNS
    assert all(len(r) == len(COLUMNS) for r in rows[1:])
    assert (
        rows[1][COLUMNS.index("station")] == "f4:12:fa:f3:57:68" and rows[2][COLUMNS.index("station")] == ""
    )
    assert rows[1][COLUMNS.index("signal_dbm")] == "-52" and rows[1][COLUMNS.index("tx_mbps")] == ""


async def test_recording_writes_to_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openwrtgui.rf.sampler.documents_dir", lambda: tmp_path)
    sampler, _ = _sampler(tmp_path)
    path = sampler.start_recording()
    assert path.parent == tmp_path / "OpenWrtGUI" and path.name.startswith("rf-ap1-radio0-")
    await sampler.tick()
    await sampler.tick()
    assert sampler.stop_recording() == path
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_recording_goes_to_the_given_folder(tmp_path: Path) -> None:
    routers = RouterStore(tmp_path / "routers.json")
    sampler = RfSampler(
        "ap1", "radio0", pool=ConnectionPool(None), routers=routers, recordings=tmp_path / "rec"
    )  # type: ignore[arg-type]
    path = sampler.start_recording()
    sampler.stop_recording()
    assert path.parent == tmp_path / "rec" and path.exists()


def test_documents_dir_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "_windows_documents", lambda: None)
    assert paths.documents_dir() == Path.home() / "Documents"
