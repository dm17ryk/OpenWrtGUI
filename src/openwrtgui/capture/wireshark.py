"""Wireshark on this PC: found where its installer puts it, fed a capture on stdin (`-k -i -`)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path


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
    """Wireshark reading a pcap stream from stdin; it shows packets as they arrive."""

    def __init__(self, path: Path) -> None:
        self._process = subprocess.Popen([str(path), "-k", "-i", "-"], stdin=subprocess.PIPE)  # noqa: S603

    def write(self, data: bytes) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(data)
        self._process.stdin.flush()

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()


def open_live(path: Path) -> LiveSink:
    return LiveSink(path)
