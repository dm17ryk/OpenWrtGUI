"""The 1.2b AP2 window's helpers on this PC (plan Task 10, R12): a listener for what the router sends, sending
to the router, iperf3.exe's arguments, the 16-bit counter check, and the iperf3 recording's sanitizing."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Literal

Proto = Literal["tcp", "udp"]
FRAME = 1514  # a full-size Ethernet frame, the most bytes one packet can carry
PACKETS = "RxGPC"  # the CPU port receives what the router sends
OCTETS = "RxGOC"
LIMIT_16 = 2**16
WRAP_32 = 2**32
DROPPED_KEYS = ("cookie", "system_info")


@dataclass
class PcListener:
    """A TCP or UDP listener on this PC that keeps every byte it receives, for the router's Send."""

    proto: Proto
    port: int
    host: str = "0.0.0.0"  # noqa: S104 - the router must reach it
    received: bytes = b""
    peers: list[tuple[str, int]] = field(default_factory=list)
    _server: asyncio.AbstractServer | None = None
    _udp: asyncio.DatagramTransport | None = None

    async def __aenter__(self) -> PcListener:
        loop = asyncio.get_running_loop()
        if self.proto == "tcp":
            self._server = await asyncio.start_server(self._client, self.host, self.port)
            self.port = self._server.sockets[0].getsockname()[1]
        else:
            listener = self

            class _Datagrams(asyncio.DatagramProtocol):
                def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                    listener.received += data
                    listener.peers.append((addr[0], addr[1]))

            transport, _ = await loop.create_datagram_endpoint(_Datagrams, local_addr=(self.host, self.port))
            self._udp = transport
            self.port = transport.get_extra_info("sockname")[1]
        return self

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.peers.append((peer[0], peer[1]))
        while chunk := await reader.read(65536):
            self.received += chunk
        writer.close()

    async def __aexit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._udp is not None:
            self._udp.close()


def send_from_pc(proto: Proto, host: str, port: int, data: bytes, timeout: float = 10.0) -> None:
    """This PC sends `data` to the router's Listen: one TCP connection, closed after, or one datagram."""
    if proto == "tcp":
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(data)
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, (host, port))


def iperf3_server_args(exe: Path, port: int = 5201) -> list[str]:
    """iperf3.exe on this PC, waiting for one test from the router."""
    return [str(exe), "-s", "-1", "-p", str(port)]


def iperf3_client_args(exe: Path, host: str, port: int = 5201, seconds: int = 5) -> list[str]:
    """iperf3.exe on this PC, testing against the router's one-shot server."""
    return [str(exe), "-c", host, "-p", str(port), "-t", str(seconds)]


@dataclass(frozen=True)
class Verdict:
    outcome: Literal["pass", "fail", "skip"]
    reason: str


def sixteen_bit_verdict(before: Mapping[str, int], after: Mapping[str, int], sent: int) -> Verdict:
    """The mt7620's packet counter is 16-bit (ports/mib.py WIDTH) when, after more full-size frames than 16
    bits can count, it still reads below 65,536 while the octet counter rose by at least the bytes sent."""
    frames = sent // FRAME
    if frames <= LIMIT_16:
        return Verdict("skip", f"iperf3 sent {sent} bytes, at most {frames} frames: too few to tell")
    for name, value in ((f"{PACKETS} before", before[PACKETS]), (f"{PACKETS} after", after[PACKETS])):
        if value >= LIMIT_16:
            return Verdict("fail", f"{name} read {value}: wider than 16 bits")
    rose = (after[OCTETS] - before[OCTETS]) % WRAP_32
    if rose < sent:
        return Verdict("fail", f"{OCTETS} rose by {rose}, less than the {sent} bytes iperf3 sent")
    return Verdict(
        "pass",
        f"{PACKETS} read {before[PACKETS]} and {after[PACKETS]} after over {frames} frames, "
        f"while {OCTETS} rose by {rose}: 16 bits",
    )


def sent_bytes(lines: Sequence[str]) -> int:
    """The bytes iperf3 sent, from its `end` event; 0 without one."""
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("event") == "end":
            data = obj.get("data") or {}
            total = data.get("sum_sent") or data.get("sum") or {}
            return int(total.get("bytes", 0))
    return 0


def _rounded(value: object) -> object:
    """Floats to 6 decimals: iperf3's long fractions read as 15-digit numbers to the IMEI check."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def sanitize_iperf3_line(line: str) -> str:
    """One iperf3 JSON line for the public recording: its cookie and system_info (the router's kernel and
    host name) left out, and its floats rounded."""
    try:
        obj = json.loads(line)
    except ValueError:
        return line
    if isinstance(obj, dict) and isinstance(obj.get("data"), dict):
        obj["data"] = {k: v for k, v in obj["data"].items() if k not in DROPPED_KEYS}
    return json.dumps(_rounded(obj), separators=(",", ":"))
