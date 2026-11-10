"""transport/comeback.py: waiting for a router to come back after a reboot or a flash, proven by a fresh
uptime (one younger than the time since the restart was armed)."""

from __future__ import annotations

from datetime import datetime

import pytest

from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import (
    CommandResult,
    HostKeyChanged,
    HostKeyInfo,
    Transport,
    TransportError,
    Unreachable,
)
from openwrtgui.transport.comeback import wait_for_reboot
from openwrtgui.transport.pool import ConnectionPool

REC = RouterRecord(id="ap2", name="AP2", host="192.168.1.2", auth="key", added_at=datetime(2026, 11, 9))


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class Router:
    """Answers `cat /proc/uptime` from a script of what each connection sees; None = unreachable."""

    def __init__(self, clock: Clock, script: list[float | None | Exception]) -> None:
        self.clock = clock
        self.script = script
        self.connects = 0

    async def factory(self, rec: RouterRecord) -> Transport:
        step = self.script[min(self.connects, len(self.script) - 1)]
        self.connects += 1
        if isinstance(step, Exception):
            raise step
        if step is None:
            raise Unreachable("no route to host")
        uptime = step

        class T:
            async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
                return CommandResult(command, f"{uptime:.2f} 1.00\n", "", 0)

            async def close(self) -> None:
                return None

        return T()  # type: ignore[return-value]


async def test_a_fresh_uptime_is_back() -> None:
    clock = Clock()
    router = Router(clock, [None, None, 4.0])
    back = await wait_for_reboot(
        ConnectionPool(router.factory), REC, armed_at=100.0, clock=clock, sleep=clock.sleep, limit_s=300
    )
    assert back is not None and back.uptime_s == 4.0 and back.elapsed_s == 15.0 and back.proof is None


async def test_an_uptime_older_than_the_arm_time_is_the_old_system() -> None:
    clock = Clock()
    router = Router(clock, [86400.0, 86405.0, 2.0])  # the reboot had not happened yet, then it had
    back = await wait_for_reboot(
        ConnectionPool(router.factory), REC, armed_at=100.0, clock=clock, sleep=clock.sleep, limit_s=300
    )
    assert back is not None and back.uptime_s == 2.0 and router.connects == 3


async def test_a_router_that_does_not_come_back() -> None:
    clock = Clock()
    router = Router(clock, [None])
    assert (
        await wait_for_reboot(
            ConnectionPool(router.factory), REC, armed_at=100.0, clock=clock, sleep=clock.sleep, limit_s=60
        )
        is None
    )
    assert clock.now - 100.0 > 60


async def test_a_changed_host_key_is_not_waited_out() -> None:
    clock = Clock()
    changed = HostKeyChanged(
        "192.168.1.2", "SHA256:old", HostKeyInfo("ssh-ed25519", "SHA256:new", "ssh-ed25519 AAAA")
    )
    router = Router(clock, [None, changed])
    with pytest.raises(HostKeyChanged):
        await wait_for_reboot(
            ConnectionPool(router.factory), REC, armed_at=100.0, clock=clock, sleep=clock.sleep, limit_s=300
        )


async def test_prove_runs_once_back_and_a_failed_read_keeps_waiting() -> None:
    clock = Clock()
    router = Router(clock, [1.0, 6.0])
    calls: list[float] = []

    async def prove(t: Transport, uptime: float) -> str:
        calls.append(uptime)
        if len(calls) == 1:
            raise TransportError("the board read did not answer yet")
        return "dlink,dwr-921-c3-uboot"

    back = await wait_for_reboot(
        ConnectionPool(router.factory),
        REC,
        armed_at=100.0,
        clock=clock,
        sleep=clock.sleep,
        limit_s=300,
        prove=prove,
    )
    assert back is not None and back.proof == "dlink,dwr-921-c3-uboot" and calls == [1.0, 6.0]
