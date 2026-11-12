"""A simulated router's files, as far as LuCI's menu asks about them (v1.0a1 D7): `ls -ldL` and `ls -A`."""

from __future__ import annotations

import shlex
from collections.abc import Mapping

from openwrtgui.transport.base import CommandResult

_MODES = {
    "executable": "-rwxr-xr-x",
    "file": "-rw-r--r--",
    "directory": "drwxr-xr-x",
    "empty directory": "drwxr-xr-x",
    "other": "prw-r--r--",  # a FIFO: the same columns as a file (a device's size would be "major, minor")
}


class SimFiles:
    def __init__(self, files: Mapping[str, str]) -> None:
        self._files = dict(files)

    def answer(self, command: str) -> CommandResult | None:
        if command.startswith("ls -ldL "):
            paths = shlex.split(command)[2:]
            lines = [
                f"{_MODES[self._files[p]]}    1 root     root          4096 Aug 13  2024 {p}"
                for p in paths
                if p in self._files
            ]
            missing = [p for p in paths if p not in self._files]
            stderr = "".join(f"ls: {p}: No such file or directory\n" for p in missing)
            return CommandResult(command, "".join(f"{line}\n" for line in lines), stderr, 1 if missing else 0)
        if command.startswith("ls -A "):
            path = shlex.split(command)[2]
            kind = self._files.get(path)
            if kind not in ("directory", "empty directory"):
                return None  # not a directory this map knows: the other handlers or the recordings answer it
            return CommandResult(command, "entry\n" if kind == "directory" else "", "", 0)
        return None
