"""AP2 faults window: faults armed the way the app arms them, on the real router, and cleared.

Run with test_ap2_firewall.py (see its docstring). The target is an address in 192.168.1.240-.250 that AP2's
ARP table and host hints do not know, with a made-up MAC, so no real device is hit; the fixture clears
everything at the end and checks AP2 is as found.
"""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest

from conftest import FwWindow
from openwrtgui.capture.service import CaptureRequest
from openwrtgui.faults.model import FaultRequest, NetemParams, TargetRef
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.ports.parse import parse_swconfig_show

pytestmark = pytest.mark.hardware

AP2 = "ap2"
MAC = "02:00:00:00:00:01"
FREE_PORT = 2  # LAN2: no link, not the app's port
PCAP_MAGIC = b"\xd4\xc3\xb2\xa1"


def _proven(result: NetApplyResult) -> None:
    failed = [f"{c.name}: {c.detail}" for c in result.checks if c.ok is not True]
    assert result.applied and result.verified, failed or result.error


async def _target(w: FwWindow) -> TargetRef:
    t = await w.connect()
    try:
        arp = (await t.run("cat /proc/net/arp")).stdout
    finally:
        await t.close()
    known = {x.ip for x in (await w.faults.state(AP2)).targets}
    for last in range(240, 251):
        ip = f"192.168.1.{last}"
        if ip not in known and f"{ip} " not in arp:
            return TargetRef(MAC, ip)
    pytest.skip("no free address in 192.168.1.240-.250")


async def _arm(w: FwWindow, req: FaultRequest) -> NetApplyResult:
    plan = await w.faults.plan_fault(AP2, req)
    print("\n" + "\n".join(plan.lines))
    result = await w.faults.apply_fault(AP2, req, plan.digest)
    print([(c.name, c.ok, c.detail) for c in result.checks], result.error)
    return result


async def test_held_l3_fault_cleared_by_router_timer(fw_window: FwWindow) -> None:
    target = await _target(fw_window)
    armed = await _arm(fw_window, FaultRequest("block", target, flow="all_in", hold_s=15))
    _proven(armed)
    family = (await fw_window.faults.state(AP2)).caps.family
    await fw_window.pool.close_all()  # the app goes away; the router's timer clears the fault
    await asyncio.sleep(20)
    t = await fw_window.connect()
    try:
        listed = await t.run(f"nft list table {family} benchfault")
        assert "chain f" not in listed.stdout, listed.stdout
        assert not (await t.run("ls /tmp/owg/fault-*.json")).ok
    finally:
        await t.close()
    assert (await fw_window.faults.state(AP2)).armed == ()


async def test_netem_to_target_and_clear(fw_window: FwWindow) -> None:
    target = await _target(fw_window)
    armed = await _arm(fw_window, FaultRequest("netem", target, netem=NetemParams(delay_ms=100)))
    _proven(armed)
    (fault,) = (await fw_window.faults.state(AP2)).armed
    plan = await fw_window.faults.plan_clear(AP2, [fault.id])
    _proven(await fw_window.faults.apply_clear(AP2, [fault.id], plan.digest))


async def test_link_down_on_free_port_held(fw_window: FwWindow) -> None:
    target = await _target(fw_window)
    armed = await _arm(fw_window, FaultRequest("link_down", target, port=FREE_PORT, hold_s=10))
    _proven(armed)
    await asyncio.sleep(15)
    t = await fw_window.connect()
    try:
        switch = parse_swconfig_show("switch0", (await t.run("swconfig dev switch0 show")).stdout)
    finally:
        await t.close()
    assert next(p for p in switch.ports if p.num == FREE_PORT).enabled is True


def _ssh_packets(data: bytes, pc_ip: str) -> int:
    """TCP packets between this PC and port 22 in an Ethernet pcap."""
    assert data[:4] == PCAP_MAGIC, data[:4]
    pc = bytes(int(x) for x in pc_ip.split("."))
    found, at = 0, 24
    while at + 16 <= len(data):
        incl = struct.unpack("<I", data[at + 8 : at + 12])[0]
        frame = data[at + 16 : at + 16 + incl]
        at += 16 + incl
        if len(frame) < 38 or frame[12:14] != b"\x08\x00" or frame[23] != 6:
            continue
        ihl = (frame[14] & 0x0F) * 4
        src, dst = frame[26:30], frame[30:34]
        sport, dport = struct.unpack(">HH", frame[14 + ihl : 18 + ihl])
        if pc in (src, dst) and 22 in (sport, dport):
            found += 1
    return found


async def test_capture_br_lan_to_pcap(fw_window: FwWindow) -> None:
    view = await fw_window.captures.start(AP2, CaptureRequest("br-lan", "", 5))
    for _ in range(60):
        done = next(v for v in fw_window.captures.list(AP2) if v.id == view.id)
        if not done.running:
            break
        await asyncio.sleep(0.5)
    assert not done.running and done.path is not None, done
    data = Path(done.path).read_bytes()
    pc_ip = (await fw_window.net.state(AP2)).pc_ip
    assert pc_ip is not None
    print(f"\n{len(data)} B captured")
    assert _ssh_packets(data, pc_ip) == 0
