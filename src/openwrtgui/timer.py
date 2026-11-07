"""Router-side timers (O15): a detached shell that sleeps, then runs its lines, so a held fault ends and a
change outside uci rolls back on time even if this PC or the app goes away. Its pid file in /tmp/owg names
it; a cancel stops that shell (the `sleep` it started then ends on its own and runs nothing)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from openwrtgui.uci import shell_quote

TIMER_DIR = "/tmp/owg"
_NAME = re.compile(r"[a-z0-9-]{1,32}")


def _check(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError("A timer name is 1 to 32 lower-case letters, digits or -")


def pid_file(name: str) -> str:
    _check(name)
    return f"{TIMER_DIR}/{name}.pid"


def arm_command(name: str, seconds: int, lines: Sequence[str]) -> str:
    """Start the timer: after `seconds` it runs `lines`, then removes every /tmp/owg/<name>.* file."""
    script = "; ".join([f"sleep {int(seconds)}", *lines, f"rm -f {TIMER_DIR}/{name}.*"])
    return (
        f"mkdir -p {TIMER_DIR} && start-stop-daemon -S -b -m -p {pid_file(name)} -x /bin/sh -- -c "
        + shell_quote(script)
    )


def cancel_command(name: str) -> str:
    return f"start-stop-daemon -K -q -p {pid_file(name)}; rm -f {pid_file(name)}"


def alive_command(name: str) -> str:
    return f'kill -0 "$(cat {pid_file(name)})"'
