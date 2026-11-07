"""tools/timer_spike.py (O15): the exact command sequence, and that it always cleans up (no router)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from openwrtgui.timer import arm_command, cancel_command
from openwrtgui.transport.base import CommandResult

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "timer_spike.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("timer_spike", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["timer_spike"] = module
    spec.loader.exec_module(module)
    return module


spike = _load()
TEST = "[ -e /tmp/owg-spike ] && echo present || echo gone"


class Router:
    """Shared by every connection: answers the file test in turn; one command can fail."""

    def __init__(self, files: list[str], fail: str | None = None) -> None:
        self.files = files
        self.fail = fail
        self.log: list[tuple[int, str]] = []
        self.connections = 0


class Conn:
    def __init__(self, router: Router) -> None:
        router.connections += 1
        self.n = router.connections
        self.router = router

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.router.log.append((self.n, command))
        if self.router.fail and command.startswith(self.router.fail):
            return CommandResult(command, "", "start-stop-daemon: not found\n", 127)
        if command == TEST:
            return CommandResult(command, self.router.files.pop(0) + "\n", "", 0)
        return CommandResult(command, "", "", 0)

    async def close(self) -> None:
        return None


async def _no_sleep(_: float) -> None:
    return None


async def test_spike_sequence_and_cleanup() -> None:
    router = Router(["gone", "present"])

    async def connect() -> Conn:
        return Conn(router)

    findings = await spike.spike(connect, _no_sleep)
    assert findings["round1"] == {"armed": True, "fired_after_disconnect": True}
    assert findings["round2"] == {"armed": True, "cancelled_from_new_connection": True}
    commands = [c for _, c in router.log]
    assert commands == [
        "touch /tmp/owg-spike",
        arm_command("spike1", 10, ["rm -f /tmp/owg-spike"]),
        TEST,
        "touch /tmp/owg-spike",
        arm_command("spike2", 30, ["rm -f /tmp/owg-spike"]),
        cancel_command("spike2"),
        TEST,
        "rm -f /tmp/owg-spike /tmp/owg/spike*",
    ]
    # round 1 tests the file on a new connection, round 2 cancels on another new one
    assert [n for n, c in router.log if c == TEST] == [2, 3]
    assert next(n for n, c in router.log if c == cancel_command("spike2")) == 3


async def test_cleanup_runs_when_a_step_fails() -> None:
    router = Router([], fail="mkdir -p /tmp/owg")

    async def connect() -> Conn:
        return Conn(router)

    findings = await spike.spike(connect, _no_sleep)
    assert findings["round1"]["armed"] is False
    assert "round2" not in findings
    assert router.log[-1][1] == "rm -f /tmp/owg-spike /tmp/owg/spike*"
