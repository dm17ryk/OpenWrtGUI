"""Router-side timers: one detached shell per timer, its pid file in /tmp/owg, cancelled by that pid."""

from __future__ import annotations

import pytest

from openwrtgui.timer import alive_command, arm_command, cancel_command


def test_arm_command_shape() -> None:
    assert arm_command("fault-a1b2c3", 30, ["swconfig dev switch0 port 2 set enable 1"]) == (
        "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/fault-a1b2c3.pid -x /bin/sh -- -c "
        "'sleep 30; swconfig dev switch0 port 2 set enable 1; rm -f /tmp/owg/fault-a1b2c3.*'"
    )


def test_cancel_and_alive() -> None:
    assert cancel_command("rb-0f0f0f") == (
        "start-stop-daemon -K -q -p /tmp/owg/rb-0f0f0f.pid; rm -f /tmp/owg/rb-0f0f0f.pid"
    )
    assert alive_command("fault-a1b2c3") == 'kill -0 "$(cat /tmp/owg/fault-a1b2c3.pid)"'


def test_quotes_survive() -> None:
    """A line with a single quote inside reaches the timer's shell unchanged."""
    command = arm_command("t1", 5, ["nft add rule inet x c comment 'owg'"])
    assert command.endswith("-c 'sleep 5; nft add rule inet x c comment '\\''owg'\\''; rm -f /tmp/owg/t1.*'")


@pytest.mark.parametrize("name", ["", "Fault", "a b", "x" * 33, "../etc", "t1\n"])
def test_names_are_checked(name: str) -> None:
    with pytest.raises(ValueError, match="A timer name is 1 to 32 lower-case letters, digits or -"):
        arm_command(name, 5, ["true"])
