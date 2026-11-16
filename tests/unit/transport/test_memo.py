"""OnceReads (v1.0c Task 6): within one refresh, a read the router already answered is not asked again."""

from __future__ import annotations

import pytest

from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.memo import once_reads

ARP = "IP address       HW type     Flags       HW address            Mask     Device\n"


class Counting:
    """Answers from a script; an answer that is an exception is raised once, then `then` answers."""

    def __init__(self, answers: dict[str, str | Exception], then: dict[str, str] | None = None) -> None:
        self.answers = dict(answers)
        self.then = then or {}
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        answer = self.answers.pop(command, None) if command in self.answers else self.then.get(command, "")
        if isinstance(answer, Exception):
            raise answer
        return CommandResult(command, answer or "", "", 0)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, stdin, "", 0)


async def test_the_same_read_is_asked_once() -> None:
    inner = Counting({"cat /proc/net/arp": ARP})
    t = once_reads(inner)  # type: ignore[arg-type]
    first = await t.run("cat /proc/net/arp")
    second = await t.run("cat /proc/net/arp")
    assert first.stdout == second.stdout == ARP
    assert inner.calls == ["cat /proc/net/arp"]


async def test_a_failed_read_is_asked_again() -> None:
    inner = Counting({"cat /proc/net/arp": TransportError("lost")}, then={"cat /proc/net/arp": ARP})
    t = once_reads(inner)  # type: ignore[arg-type]
    with pytest.raises(TransportError):
        await t.run("cat /proc/net/arp")
    assert (await t.run("cat /proc/net/arp")).stdout == ARP


async def test_input_fed_commands_are_never_kept() -> None:
    inner = Counting({})
    t = once_reads(inner)  # type: ignore[arg-type]
    await t.run_stdin("cat", "a")
    await t.run_stdin("cat", "a")
    assert inner.calls == ["cat", "cat"]


async def test_each_wrapper_starts_empty() -> None:
    inner = Counting({}, then={"cat /proc/net/arp": ARP})
    await once_reads(inner).run("cat /proc/net/arp")  # type: ignore[arg-type]
    await once_reads(inner).run("cat /proc/net/arp")  # type: ignore[arg-type]
    assert inner.calls == ["cat /proc/net/arp", "cat /proc/net/arp"]
