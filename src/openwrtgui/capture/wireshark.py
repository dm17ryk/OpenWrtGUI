"""Wireshark on this PC: found where its installer puts it, fed a capture on stdin (`-k -i -`)."""

from __future__ import annotations

import contextlib
import os
import queue
import shutil
import struct
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

QUEUE_BYTES = 4 * 1024 * 1024  # packets waiting for Wireshark at most; past it they are dropped (v1.0c D6)
JOIN_S = 2.0
_HEADER = 24  # a pcap file header
_RECORD = 16  # a pcap record header: seconds, fraction, captured length, original length
_ENDIAN = {  # the magic of a pcap stream (microsecond or nanosecond), in either byte order
    bytes.fromhex("d4c3b2a1"): "<",
    bytes.fromhex("4d3cb2a1"): "<",
    bytes.fromhex("a1b2c3d4"): ">",
    bytes.fromhex("a1b23c4d"): ">",
}


def find_wireshark(
    env: Mapping[str, str] = os.environ, which: Callable[[str], str | None] = shutil.which
) -> Path | None:
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = env.get(var)
        if root and (exe := Path(root) / "Wireshark" / "Wireshark.exe").is_file():
            return exe
    found = which("Wireshark")
    return Path(found) if found else None


class _Records:
    """Cuts a pcap byte stream into its file header and whole packet records, so a drop removes packets and
    never part of one: pcap has no marker to find the next record after a cut (the final review). A stream
    that is not pcap passes as it comes."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._endian: str | None = None
        self._opaque = False

    def feed(self, data: bytes) -> list[bytes]:
        if self._opaque:
            return [data]
        self._buf += data
        out: list[bytes] = []
        if self._endian is None:
            if len(self._buf) < _HEADER:
                return out
            endian = _ENDIAN.get(bytes(self._buf[:4]))
            if endian is None:
                self._opaque = True
                whole = bytes(self._buf)
                self._buf.clear()
                return [whole]
            self._endian = endian
            out.append(bytes(self._buf[:_HEADER]))
            del self._buf[:_HEADER]
        while len(self._buf) >= _RECORD:
            (captured,) = struct.unpack_from(f"{self._endian}I", self._buf, 8)
            end = _RECORD + captured
            if len(self._buf) < end:
                break
            out.append(bytes(self._buf[:end]))
            del self._buf[:end]
        return out


class LiveSink:
    """Wireshark reading a pcap stream from stdin; it shows packets as they arrive.

    The pipe is fed from a thread (v1.0c Task 7, #12): a write never waits for Wireshark. Packets past the
    byte budget are counted in `dropped` and never reach Wireshark (D6), whole records at a time, so its view
    stays a valid capture; the capture itself goes on. Once Wireshark has gone (its pipe broke), the next
    write raises that OSError, which ends the capture. The feeder owns stdin and closes it itself."""

    def __init__(
        self,
        path: Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        queue_bytes: int = QUEUE_BYTES,
        join_s: float = JOIN_S,
    ) -> None:
        self._process = popen([str(path), "-k", "-i", "-"], stdin=subprocess.PIPE)
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._records = _Records()
        self._budget = queue_bytes
        self._queued = 0
        self._lock = threading.Lock()
        self._first = True
        self._join_s = join_s
        self._error: OSError | None = None
        self.dropped = 0
        self._thread = threading.Thread(target=self._feed, name="wireshark-feed", daemon=True)
        self._thread.start()

    def _feed(self) -> None:
        stdin = self._process.stdin
        try:
            while (unit := self._queue.get()) is not None:
                with self._lock:
                    self._queued -= len(unit)
                stdin.write(unit)
                stdin.flush()
        except OSError as exc:  # Wireshark was closed: its pipe broke
            self._error = exc
        finally:
            with contextlib.suppress(OSError):
                stdin.close()

    def write(self, data: bytes) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Wireshark was started without a pipe")
        if self._error is not None:
            raise self._error
        for unit in self._records.feed(data):
            keep = self._first  # the file header always goes: without it Wireshark reads nothing
            self._first = False
            with self._lock:
                if not keep and self._queued + len(unit) > self._budget:
                    self.dropped += len(unit)
                    continue
                self._queued += len(unit)
            self._queue.put(unit)

    def close(self) -> None:
        """Ends the stream after what is queued; a Wireshark that reads nothing is not waited for past join_s
        (its feeder ends when Wireshark does). Called off the event loop (`capture/service.py`)."""
        self._queue.put(None)
        self._thread.join(self._join_s)


def open_live(path: Path) -> LiveSink:
    return LiveSink(path)
