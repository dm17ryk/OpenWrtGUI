"""The 1.2b AP2 window, Part 1, wired (plan Task 12, R12): Throughput against this PC, the mt7620's 16-bit
packet counters, the Traffic generator both ways, and the SIP ALG switch off and on.

    uv run pytest -m hardware tests/hardware/test_ap2_tools.py --router 192.168.1.2 --identity <key> \
        --known-hosts <file> --allow-writes --txctl-told --pc-iperf3 <path to iperf3.exe> -v -s

Only in a window Dmitry OK'd at the time, with Bench Guard clear and the txctl session told. Windows Firewall
must let 192.168.1.2 reach this PC on TCP and UDP 5201 and 9101 (Dmitry's own change if it does not). The
commands are the app's own (tools/throughput.py, tools/traffic.py) over AP2's SSH streams; their lines are
recorded, sanitized, for the contract tests. Nothing here touches the radio.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from pathlib import Path

import pytest
from tools_window import (
    PcListener,
    Proto,
    iperf3_client_args,
    iperf3_server_args,
    sanitize_iperf3_line,
    send_from_pc,
    sent_bytes,
    sixteen_bit_verdict,
)

from conftest import AP2, FwWindow
from openwrtgui.fw.commands import NFT_TEXT
from openwrtgui.fw.sip import SipAlgRequest
from openwrtgui.ports.parse import parse_port_mib
from openwrtgui.system.parse import zone_helpers
from openwrtgui.tools.sessions import ToolSessions, ToolSessionView
from openwrtgui.tools.throughput import ThroughputRequest, iperf3_command, parse_iperf3_line
from openwrtgui.tools.traffic import ListenRequest, SendRequest, listen_command, listen_parser, send_command
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
TOOLS_JSON = FIXTURES / "tools.json"
MIB_JSON = FIXTURES / "mib.json"
AP2_ID = "ap2"
CPU_PORT = 6  # the mt7620's CPU port on AP2 (ports/mib.py WIDTH's note)
SHOW = "swconfig dev switch0 show"
TEN = ["amanda", "RAS", "Q.931", "irc", "netbios-ns", "pptp", "sane", "sip", "snmp", "tftp"]
LISTEN_PORT = 9100
PC_PORT = 9101
OWG_TEST = b"owg-test\n"
PROTOS: tuple[Proto, ...] = ("tcp", "udp")


def _view(kind: str = "throughput") -> ToolSessionView:
    return ToolSessionView(
        id="w",
        router_id="ap2",
        kind=kind,
        title="window",
        command="",
        started_at=0,
        ends_at=0,
        running=True,  # type: ignore[arg-type]
    )


async def _stream_lines(t: SshTransport, command: str) -> tuple[list[str], int | None]:
    """A session's command on AP2 until the router's own `timeout` ends it: its lines, without the pid."""
    stream = await t.stream(command)
    data = b""
    try:
        while chunk := await stream.read(65536):
            data += chunk
    finally:
        await stream.close()
    lines = data.decode(errors="replace").splitlines()
    return [line for line in lines if not line.startswith("OWG-PID ")], stream.exit_status


async def _pc_address(t: SshTransport) -> str:
    return (await t.run("echo $SSH_CONNECTION")).stdout.split()[0]


def _iperf3(request: pytest.FixtureRequest) -> Path:
    exe: Path | None = request.config.getoption("--pc-iperf3")
    if exe is None or not exe.is_file():
        pytest.skip("pass --pc-iperf3 <path to iperf3.exe on this PC>")
    return exe


def _record(path: Path, key: str, value: object) -> None:
    recorded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    recorded[key] = value
    path.write_text(json.dumps(recorded, indent=1) + "\n", encoding="utf-8")


async def _client_run(t: SshTransport, exe: Path, req: ThroughputRequest) -> list[str]:
    """The router's iperf3 client against this PC's one-shot server."""
    server = await asyncio.create_subprocess_exec(
        *iperf3_server_args(exe), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.sleep(1)
        command, _limit = iperf3_command(req)
        lines, status = await _stream_lines(t, command)
    finally:
        with contextlib.suppress(ProcessLookupError):
            server.kill()
        await server.wait()
    assert status == 0, lines[-3:]
    return lines


def _parsed(lines: list[str]) -> ToolSessionView:
    view = _view()
    for line in lines:
        view = parse_iperf3_line(view, line)
    return view


async def test_throughput_against_this_pc(ap2_rw: SshTransport, request: pytest.FixtureRequest) -> None:
    exe = _iperf3(request)
    pc = await _pc_address(ap2_rw)
    runs = {
        "client_tcp": ThroughputRequest(mode="client", host=pc, duration_s=5),
        "client_tcp_reverse": ThroughputRequest(mode="client", host=pc, duration_s=5, reverse=True),
        "client_udp": ThroughputRequest(mode="client", host=pc, duration_s=5, protocol="udp", udp_mbps=10),
    }
    for key, req in runs.items():
        lines = await _client_run(ap2_rw, exe, req)
        view = _parsed(lines)
        print(f"\n{key}: {view.summary}")
        assert view.error is None and view.summary is not None and len(view.intervals) >= 4, view
        assert (view.summary.sent_mbps or 0) > 0 or (view.summary.received_mbps or 0) > 0
        _record(TOOLS_JSON, key, [sanitize_iperf3_line(line) for line in lines])
    # the router as the server: this PC's iperf3 tests against it
    command, _limit = iperf3_command(ThroughputRequest(mode="server"))
    session = asyncio.create_task(_stream_lines(ap2_rw, command))
    await asyncio.sleep(2)
    client = await asyncio.create_subprocess_exec(
        *iperf3_client_args(exe, "192.168.1.2"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await client.communicate()
    lines, status = await session
    print(out.decode(errors="replace")[-400:])
    view = _parsed(lines)
    assert status == 0 and view.error is None and view.summary is not None, view
    _record(TOOLS_JSON, "server", [sanitize_iperf3_line(line) for line in lines])


async def test_port_counters_are_16_bit(ap2_rw: SshTransport, request: pytest.FixtureRequest) -> None:
    """A 60 s TCP run from the router to this PC between two reads of the CPU port's counters (WIDTH)."""
    exe = _iperf3(request)
    pc = await _pc_address(ap2_rw)
    first = (await ap2_rw.run(SHOW)).stdout
    lines = await _client_run(ap2_rw, exe, ThroughputRequest(mode="client", host=pc, duration_s=60))
    second = (await ap2_rw.run(SHOW)).stdout
    _record(MIB_JSON, "before", first)
    _record(MIB_JSON, "after", second)
    verdict = sixteen_bit_verdict(
        parse_port_mib(first)[CPU_PORT], parse_port_mib(second)[CPU_PORT], sent_bytes(lines)
    )
    print(f"\n{verdict.outcome}: {verdict.reason}")
    if verdict.outcome == "skip":
        pytest.skip(verdict.reason)
    assert verdict.outcome == "pass", verdict.reason


async def _listen(t: SshTransport, proto: Proto, pc: str) -> list[str]:
    command, _limit = listen_command(ListenRequest(protocol=proto, port=LISTEN_PORT, duration_s=20))
    session = asyncio.create_task(_stream_lines(t, command))
    await asyncio.sleep(3)  # socat binds
    await asyncio.to_thread(send_from_pc, proto, AP2, LISTEN_PORT, OWG_TEST)
    lines, status = await session
    assert status == 137, lines[-3:]  # the router's timeout ends a listen
    parse = listen_parser()
    view = _view("listen")
    for line in lines:
        view = parse(view, line)
    assert [(p.address, p.bytes, p.first_hex) for p in view.peers] == [(pc, 9, OWG_TEST.hex())], view
    return lines


async def test_traffic_both_ways(ap2_rw: SshTransport) -> None:
    pc = await _pc_address(ap2_rw)
    for proto in PROTOS:
        _record(TOOLS_JSON, f"listen_{proto}", await _listen(ap2_rw, proto, pc))
    for proto in PROTOS:
        async with PcListener(proto, PC_PORT) as listener:
            zeros = SendRequest(protocol=proto, host=pc, port=PC_PORT, what="bytes", count=1000)
            assert (await ap2_rw.run(send_command(zeros), timeout=40)).ok
            await asyncio.sleep(1)
            assert listener.received == bytes(1000), len(listener.received)
            listener.received = b""
            text = SendRequest(protocol=proto, host=pc, port=PC_PORT, what="text", text="owg-line")
            assert (await ap2_rw.run(send_command(text), timeout=40)).ok
            await asyncio.sleep(1)
            assert listener.received == b"owg-line\n"


async def _running(w: FwWindow, program: str) -> str:
    t = await w.connect()
    try:
        return (await t.run(f"pidof {program}")).stdout.strip()
    finally:
        await t.close()


async def test_the_engine_stops_a_session_on_ap2(fw_window: FwWindow) -> None:
    """Final review I3: the app's ToolSessions on AP2. Stop's `kill <pid>` ends a waiting iperf3 server
    (BusyBox `timeout` keeps the pid, R2) with no error. A Listen stopped while a peer holds its connection
    open ends its listener at once, and the peer's child by the listen's own limit (the security review's
    per-child limit)."""
    w = fw_window
    sessions = ToolSessions(pool=w.pool, routers=w.routers, guard=w.guard, audit=w.audit)
    command, limit = iperf3_command(ThroughputRequest(mode="server"))
    view = await sessions.start(
        AP2_ID, kind="throughput", title="Throughput", command=command, limit_s=limit, parse=parse_iperf3_line
    )
    await asyncio.sleep(3)
    assert await _running(w, "iperf3"), "iperf3 -s did not start"
    done = await sessions.stop(view.id)
    print(f"\nthroughput stopped: error={done.error} notes={done.notes}")
    assert done.running is False and done.error is None, done
    await asyncio.sleep(1)
    assert await _running(w, "iperf3") == "", "iperf3 is still running after Stop"

    listen_s = 20
    command, limit = listen_command(ListenRequest(protocol="tcp", port=LISTEN_PORT, duration_s=listen_s))
    view = await sessions.start(
        AP2_ID, kind="listen", title="Traffic listen", command=command, limit_s=limit, parse=listen_parser()
    )
    started = asyncio.get_running_loop().time()
    await asyncio.sleep(3)
    held = await asyncio.to_thread(socket.create_connection, (AP2, LISTEN_PORT), 10)
    try:
        held.sendall(OWG_TEST)
        await asyncio.sleep(2)
        done = await sessions.stop(view.id)
        print(f"listen stopped: error={done.error} peers={done.peers} socat={await _running(w, 'socat')}")
        assert done.running is False and done.error is None, done
        left = listen_s + 5 - (asyncio.get_running_loop().time() - started)
        await asyncio.sleep(max(0.0, left))
        assert await _running(w, "socat") == "", "a peer's socat child outlived the listen's limit"
    finally:
        held.close()


async def test_sip_alg_off_and_on(fw_window: FwWindow) -> None:
    """lan's SIP ALG off and on again through the app's FirewallService; fw_window checks the firewall config
    is as found afterwards."""
    w = fw_window
    for on, expected in ((False, [h for h in TEN if h != "sip"]), (True, TEN)):
        req = SipAlgRequest(zone="lan", on=on)
        plan = await w.fw.plan_sip_alg(AP2_ID, req)
        print("\n" + "\n".join(plan.lines))
        result = await w.fw.apply_sip_alg(AP2_ID, req, plan.digest)
        assert result.applied and result.verified, [f"{c.name}: {c.detail}" for c in result.checks]
        t = await w.connect()
        try:
            assert zone_helpers((await t.run(NFT_TEXT)).stdout)["lan"] == expected
        finally:
            await t.close()
