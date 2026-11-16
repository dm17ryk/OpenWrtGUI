"""Wireshark on this PC: found where its installer puts it, fed a capture on stdin (`-k -i -`)."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

QUEUE_CHUNKS = 64  # chunks of up to 64 KiB waiting for Wireshark: about 4 MiB (v1.0c D6)
JOIN_S = 2.0


def find_wireshark(
    env: Mapping[str, str] = os.environ, which: Callable[[str], str | None] = shutil.which
) -> Path | None:
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = env.get(var)
        if root and (exe := Path(root) / "Wireshark" / "Wireshark.exe").is_file():
            return exe
    found = which("Wireshark")
    return Path(found) if found else None


class LiveSink:
    """Wireshark reading a pcap stream from stdin; it shows packets as they arrive.

    The pipe is fed from a thread (v1.0c Task 7, #12): a write never waits for Wireshark. Chunks that do not
    fit the queue are counted in `dropped` and never reach Wireshark (D6); the capture itself goes on. Once
    Wireshark has gone (its pipe broke), the next write raises that OSError, which ends the capture."""

    def __init__(
        self,
        path: Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        queue_chunks: int = QUEUE_CHUNKS,
    ) -> None:
        self._process = popen([str(path), "-k", "-i", "-"], stdin=subprocess.PIPE)
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_chunks)
        self._error: OSError | None = None
        self._stop = threading.Event()
        self.dropped = 0
        self._thread = threading.Thread(target=self._feed, name="wireshark-feed", daemon=True)
        self._thread.start()

    def _feed(self) -> None:
        stdin = self._process.stdin
        while not self._stop.is_set():
            chunk = self._queue.get()
            if chunk is None:
                return
            try:
                stdin.write(chunk)
                stdin.flush()
            except OSError as exc:  # Wireshark was closed: its pipe broke
                self._error = exc
                return

    def write(self, data: bytes) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Wireshark was started without a pipe")
        if self._error is not None:
            raise self._error
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            self.dropped += len(data)

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            self._stop.set()  # the feeder ends after the chunk it is writing
        self._thread.join(JOIN_S)
        if self._process.stdin is not None:
            self._process.stdin.close()


def open_live(path: Path) -> LiveSink:
    return LiveSink(path)
