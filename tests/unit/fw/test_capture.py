"""Capture: tcpdump over a binary SSH stream to a .pcap file or Wireshark, never the app's own SSH."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fwenv import FwEnv

from openwrtgui.capture.service import CaptureRequest, CaptureService, capture_command
from openwrtgui.capture.wireshark import find_wireshark
from openwrtgui.simwifi import SimWifi
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import BytesStream, ReplayTransport
from openwrtgui.wifi.model import ChannelSelection, RadioRequest

PCAP_MAGIC = bytes.fromhex("d4c3b2a1")


def _captures(env: FwEnv, tmp_path: Path, **kw: object) -> CaptureService:
    return CaptureService(
        pool=env.pool,
        routers=env.routers,
        guard=env.guard,
        audit=env.audit,
        net=env.net,
        documents=tmp_path / "Documents",
        wireshark=lambda: None,
        clock=env.clock.now,
        **kw,  # type: ignore[arg-type]
    )


async def _done(service: CaptureService, capture_id: str) -> None:
    for _ in range(100):
        if not next(v for v in service.list_all() if v.id == capture_id).running:
            return
        await asyncio.sleep(0)
    raise AssertionError("the capture did not end")


def test_filter_excludes_own_ssh() -> None:
    assert capture_command(CaptureRequest("br-lan", "udp port 5060", 10), "192.168.1.10", 22) == (
        "timeout 10 tcpdump -i br-lan -U -s 0 -w - "
        "'not (host 192.168.1.10 and tcp port 22) and (udp port 5060)'"
    )
    assert capture_command(CaptureRequest("phy0-ap0", "", 60), "192.168.1.10", 22) == (
        "timeout 60 tcpdump -i phy0-ap0 -U -s 0 -w - 'not (host 192.168.1.10 and tcp port 22)'"
    )


def test_filter_charset_and_duration_refused() -> None:
    text = r"^A filter uses letters, digits, spaces and \. : / \( \) ! & \| < > = \[ \] -$"
    with pytest.raises(ValueError, match=text):
        capture_command(CaptureRequest("br-lan", "udp; reboot", 10), "192.168.1.10", 22)
    with pytest.raises(ValueError, match="^A capture runs 1 to 3600 s$"):
        capture_command(CaptureRequest("br-lan", "", 0), "192.168.1.10", 22)


def test_capture_refused_when_the_pc_address_is_unknown() -> None:
    # without it the app's own SSH could not be left out (Review Focus 2)
    with pytest.raises(
        ValueError, match="^Could not tell this PC's address, so the capture cannot leave out"
    ):
        capture_command(CaptureRequest("br-lan", "", 10), None, 22)


async def test_device_must_be_one_the_router_has(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path)
    for device in ("br-lan; reboot", "../../x", "eth9"):
        with pytest.raises(ValueError, match=r"^AP1 · bench has no network device "):
            await service.start("ap1", CaptureRequest(device, "", 3))
    assert not (tmp_path / "Documents").exists()  # nothing written before the check
    assert not [line for line in env.audit_lines() if line.startswith("capture")]
    view = await service.start("ap1", CaptureRequest("br-lan", "", 3))  # the refusals freed the router
    await _done(service, view.id)


async def test_capture_to_file_in_sim(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path)
    assert "br-lan" in await service.devices("ap1") and "mon0" in await service.devices("ap1")
    view = await service.start("ap1", CaptureRequest("br-lan", "udp port 5060", 3))
    await _done(service, view.id)
    done = next(v for v in service.list("ap1") if v.id == view.id)
    assert (
        done.path is not None and Path(done.path).parent == tmp_path / "Documents" / "OpenWrtGUI" / "captures"
    )
    assert Path(done.path).name.startswith("ap1-br-lan-") and Path(done.path).suffix == ".pcap"
    assert Path(done.path).read_bytes()[:4] == PCAP_MAGIC and done.bytes == Path(done.path).stat().st_size
    lines = [line for line in env.audit_lines() if line.startswith("capture")]
    assert lines == ["capture br-lan 'udp port 5060'", f"capture stopped {done.bytes} B"]


async def test_one_capture_per_router(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path)
    await service.start("ap1", CaptureRequest("br-lan", "", 3))
    with pytest.raises(ValueError, match="^A capture is already running on AP1 · bench$"):
        await service.start("ap1", CaptureRequest("eth0.1", "", 3))


async def test_capture_runs_while_guard_live(env: FwEnv, tmp_path: Path) -> None:
    env.go_live()
    service = _captures(env, tmp_path)
    view = await service.start("ap1", CaptureRequest("br-lan", "", 3))
    await _done(service, view.id)
    assert next(v for v in service.list("ap1") if v.id == view.id).error is None


async def test_mon0_refused_while_guard_live(env: FwEnv, tmp_path: Path) -> None:
    env.go_live()
    with pytest.raises(
        ValueError, match=r"^mon0 needs a monitor interface on the radio; not while dima_night\.py"
    ):
        await _captures(env, tmp_path).start("ap1", CaptureRequest("mon0", "", 3))


async def test_mon0_created_and_removed(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path)
    view = await service.start("ap1", CaptureRequest("mon0", "", 3))
    await _done(service, view.id)
    lines = env.audit_lines()
    assert any("iw phy phy0 interface add owgmon0 type monitor" in line for line in lines)
    assert "iw dev owgmon0 del" in lines
    assert lines.index("iw dev owgmon0 del") > next(
        i for i, line in enumerate(lines) if line.startswith("capture owgmon0")
    )


class _HeldStream:
    """A capture that runs until the test ends it."""

    exit_status: int | None = 124
    stderr = ""

    def __init__(self) -> None:
        self.ended = asyncio.Event()

    async def read(self, n: int) -> bytes:
        await self.ended.wait()
        return b""

    async def close(self) -> None:
        self.ended.set()


class _DiedStream:
    """tcpdump on owgmon0 when a Wi-Fi reload removes the interface: some frames, then exit 1."""

    exit_status: int | None = 1
    stderr = "tcpdump: listening on owgmon0\ntcpdump: pcap_loop: The interface disappeared\n"

    def __init__(self) -> None:
        self._chunks = [PCAP_MAGIC + bytes(20)]

    async def read(self, n: int) -> bytes:
        return self._chunks.pop() if self._chunks else b""

    async def close(self) -> None:
        return None


async def test_mon0_capture_that_loses_its_monitor_says_so(
    env: FwEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review I9: a reload during a mon0 capture ends it early; the capture must not look complete."""

    async def stream(self: ReplayTransport, command: str) -> _DiedStream:
        return _DiedStream()

    monkeypatch.setattr(ReplayTransport, "stream", stream)
    service = _captures(env, tmp_path)
    view = await service.start("ap1", CaptureRequest("mon0", "", 60))
    await _done(service, view.id)
    done = next(v for v in service.list("ap1") if v.id == view.id)
    assert done.bytes > 0
    assert done.error == (
        "mon0 went away (a Wi-Fi reload removes the monitor interface): the capture ended early. "
        "tcpdump: pcap_loop: The interface disappeared"
    )


async def test_a_mon0_capture_that_cannot_remove_its_monitor_says_so(
    env: FwEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #59 review: a refused `iw dev owgmon0 del` is tried again, and a monitor left behind is reported."""
    held = _HeldStream()

    async def stream(self: ReplayTransport, command: str) -> _HeldStream:
        return held

    original = SimWifi._one

    def refuse_del(self: SimWifi, p: str) -> CommandResult | None:
        if p == "iw dev owgmon0 del":
            return CommandResult(p, "", "command failed: Device or resource busy (-16)\n", 240)
        return original(self, p)

    monkeypatch.setattr(ReplayTransport, "stream", stream)
    monkeypatch.setattr(SimWifi, "_one", refuse_del)
    service = _captures(env, tmp_path)
    view = await service.start("ap1", CaptureRequest("mon0", "", 60))
    held.ended.set()
    await _done(service, view.id)
    done = next(v for v in service.list("ap1") if v.id == view.id)
    assert done.error is not None and "owgmon0 is still on AP1" in done.error, done.error
    assert env.audit_lines().count("iw dev owgmon0 del") == 2


async def test_mon0_writes_wait_for_the_router_write_lock(
    env: FwEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a Wi-Fi or firewall apply in flight holds it: the monitor interface must not interleave with it
    held = _HeldStream()

    async def stream(self: ReplayTransport, command: str) -> _HeldStream:
        return held

    monkeypatch.setattr(ReplayTransport, "stream", stream)
    service = _captures(env, tmp_path)
    lock = env.pool.write_lock("ap1")
    async with lock:
        start = asyncio.create_task(service.start("ap1", CaptureRequest("mon0", "", 3)))
        for _ in range(50):
            await asyncio.sleep(0)
        assert not any("interface add owgmon0" in line for line in env.audit_lines())
    view = await start
    async with lock:
        held.ended.set()
        for _ in range(50):
            await asyncio.sleep(0)
        assert "iw dev owgmon0 del" not in env.audit_lines()
    await _done(service, view.id)
    assert "iw dev owgmon0 del" in env.audit_lines()


async def test_beacon_check_keeps_a_capture_monitor(
    env: FwEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.7 plan D11: an Apply's beacon check during a mon0 capture uses the same owgmon0 and leaves it."""
    held = _HeldStream()

    async def stream(self: ReplayTransport, command: str) -> _HeldStream:
        return held

    monkeypatch.setattr(ReplayTransport, "stream", stream)
    service = _captures(env, tmp_path, monitors=env.wifi.monitors)
    view = await service.start("ap1", CaptureRequest("mon0", "", 60))
    state = await env.wifi.state("ap1")
    radio = state.radios[0]
    now = radio.actual.channel if radio.actual else None
    channel = next(c for c in radio.limits.channels if c != now)
    req = RadioRequest(radio=radio.name, channels=ChannelSelection.of(channel))
    result = await env.wifi.apply("ap1", req)
    beacon = next(c for c in result.checks if c.name == "beacon rate")
    assert beacon.ok, beacon.detail
    assert "iw dev owgmon0 del" not in env.audit_lines()  # the capture's monitor is still there
    held.ended.set()
    await _done(service, view.id)
    assert env.audit_lines().count("iw dev owgmon0 del") == 1


async def test_a_capture_that_cannot_start_leaves_nothing(
    env: FwEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(self: ReplayTransport, command: str) -> BytesStream:
        raise TransportError("SSH channel open failed")

    monkeypatch.setattr(ReplayTransport, "stream", refused)
    service = _captures(env, tmp_path)
    with pytest.raises(TransportError):
        await service.start("ap1", CaptureRequest("mon0", "", 3))
    assert "iw dev owgmon0 del" in env.audit_lines()  # the monitor interface it made is gone again
    folder = tmp_path / "Documents" / "OpenWrtGUI" / "captures"
    assert not folder.exists() or not list(folder.iterdir())  # no empty .pcap, no open file


async def test_captures_in_the_same_second_keep_both_files(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path)  # the simulated clock does not move between them
    first = await service.start("ap1", CaptureRequest("br-lan", "", 3))
    await _done(service, first.id)
    second = await service.start("ap1", CaptureRequest("br-lan", "", 3))
    await _done(service, second.id)
    paths = {v.path for v in service.list("ap1")}
    assert len(paths) == 2 and all(p is not None and Path(p).stat().st_size for p in paths)


async def test_stops_at_size_cap(env: FwEnv, tmp_path: Path) -> None:
    service = _captures(env, tmp_path, max_bytes=30)
    view = await service.start("ap1", CaptureRequest("br-lan", "", 3))
    await _done(service, view.id)
    done = next(v for v in service.list("ap1") if v.id == view.id)
    assert done.error == "Stopped at the size cap (30 B)" and done.bytes <= 30 + 65536


def test_wireshark_found_in_program_files(tmp_path: Path) -> None:
    exe = tmp_path / "Wireshark" / "Wireshark.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert find_wireshark({"ProgramFiles": str(tmp_path)}) == exe
    assert find_wireshark({"ProgramFiles": str(tmp_path / "none")}, which=lambda _: None) is None
