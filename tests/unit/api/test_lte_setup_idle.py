"""#93: whether an LTE setup runs (netifd's qmi.sh or a uqmi it started), the read Recover waits on before
each step."""

from __future__ import annotations

import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.lte import commands as c
from openwrtgui.transport.base import CommandResult, TransportError


class _Answers:
    """A transport that answers the setup read with one fixed result, or raises."""

    def __init__(self, stdout: str | None) -> None:
        self.stdout = stdout
        self.sent: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.sent.append(command)
        if self.stdout is None:
            raise TransportError("connection lost")
        return CommandResult(command, self.stdout, "", 0 if self.stdout.strip() not in ("", "0") else 1)


@pytest.mark.parametrize(("stdout", "idle"), [("0\n", True), ("1\n", False), ("2\n", False)])
async def test_setup_idle_reads_the_process_count(ctx: AppContext, stdout: str, idle: bool) -> None:
    t = _Answers(stdout)
    assert await ctx.lte.setup_idle(t) is idle  # type: ignore[arg-type]
    assert t.sent == [c.SETUP_RUNNING]


@pytest.mark.parametrize("stdout", ["garbage\n", ""])
async def test_setup_idle_is_false_on_an_odd_answer(ctx: AppContext, stdout: str) -> None:
    """Review Focus 3: a step must not cut off what it cannot see."""
    assert await ctx.lte.setup_idle(_Answers(stdout)) is False  # type: ignore[arg-type]


async def test_setup_idle_lets_a_dropped_router_through(ctx: AppContext) -> None:
    """Final review I3: a router that does not answer is not "a setup runs"; Recover fails the job instead."""
    with pytest.raises(TransportError):
        await ctx.lte.setup_idle(_Answers(None))  # type: ignore[arg-type]


def test_the_setup_read_is_read_only() -> None:
    assert is_read_only_command(c.SETUP_RUNNING)
