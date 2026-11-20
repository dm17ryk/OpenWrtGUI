"""The 1.2b AP2 window's own helpers, offline (plan Task 10): this PC's listener, the iperf3.exe runner, the
16-bit counter check and the iperf3 recording's sanitizing."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

from tools_window import (
    PcListener,
    iperf3_client_args,
    iperf3_server_args,
    sanitize_iperf3_line,
    send_from_pc,
    sent_bytes,
    sixteen_bit_verdict,
)


async def _until(predicate, seconds: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    for _ in range(int(seconds * 100)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("not in time")


async def test_the_listener_keeps_what_a_tcp_peer_sends() -> None:
    async with PcListener("tcp", 0, host="127.0.0.1") as listener:
        await asyncio.to_thread(send_from_pc, "tcp", "127.0.0.1", listener.port, b"owg-test\n")
        await _until(lambda: listener.received == b"owg-test\n")
        assert listener.peers and listener.peers[0][0] == "127.0.0.1"


async def test_the_listener_keeps_udp_datagrams() -> None:
    async with PcListener("udp", 0, host="127.0.0.1") as listener:
        await asyncio.to_thread(send_from_pc, "udp", "127.0.0.1", listener.port, b"abc")
        await asyncio.to_thread(send_from_pc, "udp", "127.0.0.1", listener.port, b"def")
        await _until(lambda: listener.received == b"abcdef")


def test_send_from_pc_reaches_a_plain_socket() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        send_from_pc("tcp", "127.0.0.1", server.getsockname()[1], b"x")
        peer, _ = server.accept()
        with peer:
            assert peer.recv(10) == b"x"


def test_the_iperf3_runner() -> None:
    exe = Path("C:/tools/iperf3.exe")
    assert iperf3_server_args(exe) == [str(exe), "-s", "-1", "-p", "5201"]
    assert iperf3_client_args(exe, "192.168.1.2", seconds=5) == [
        str(exe),
        "-c",
        "192.168.1.2",
        "-p",
        "5201",
        "-t",
        "5",
    ]


ENOUGH = 70_000 * 1514


def test_16_bit_counters_pass() -> None:
    before = {"RxGPC": 1200, "RxGOC": 4_000_000_000}
    after = {"RxGPC": 30_000, "RxGOC": (4_000_000_000 + ENOUGH + 5000) % 2**32}  # the octets wrapped too
    verdict = sixteen_bit_verdict(before, after, ENOUGH)
    assert verdict.outcome == "pass", verdict.reason


def test_a_packet_counter_past_16_bits_fails() -> None:
    verdict = sixteen_bit_verdict({"RxGPC": 1200, "RxGOC": 0}, {"RxGPC": 71_200, "RxGOC": ENOUGH}, ENOUGH)
    assert verdict.outcome == "fail" and "71200" in verdict.reason


def test_octets_that_did_not_rise_enough_fail() -> None:
    verdict = sixteen_bit_verdict({"RxGPC": 1, "RxGOC": 0}, {"RxGPC": 2, "RxGOC": 1000}, ENOUGH)
    assert verdict.outcome == "fail"


def test_too_little_traffic_skips() -> None:
    verdict = sixteen_bit_verdict({"RxGPC": 1, "RxGOC": 0}, {"RxGPC": 2, "RxGOC": 10**8}, 65_536 * 1514)
    assert verdict.outcome == "skip"


def test_sent_bytes_from_the_end_event() -> None:
    lines = [
        json.dumps({"event": "interval", "data": {"sum": {"bytes": 10}}}),
        json.dumps({"event": "end", "data": {"sum_sent": {"bytes": 123_456_789}}}),
    ]
    assert sent_bytes(lines) == 123_456_789
    assert sent_bytes(["not json"]) == 0


def test_the_recording_leaves_out_the_cookie_and_system_info() -> None:
    start = {
        "event": "start",
        "data": {"cookie": "abc", "system_info": "Linux owg 6.6", "version": "iperf 3.21"},
    }
    clean = json.loads(sanitize_iperf3_line(json.dumps(start)))
    assert clean == {"event": "start", "data": {"version": "iperf 3.21"}}
    assert sanitize_iperf3_line("plain text") == "plain text"
