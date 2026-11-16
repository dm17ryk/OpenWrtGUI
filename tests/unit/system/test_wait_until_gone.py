"""A router counts as gone after three failed logins in a row (v0.6c minor #37, v1.0b2 D9)."""

from __future__ import annotations

from datetime import datetime

from openwrtgui.store.routers import RouterRecord
from openwrtgui.system.restore import wait_until_gone
from openwrtgui.transport.base import CommandResult, TransportError

REC = RouterRecord(
    id="ap2", name="AP2", host="192.168.1.2", auth="key", added_at=datetime(2026, 11, 16, 9, 0)
)


class _Up:
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return CommandResult(command, "", "", 0)

    async def close(self) -> None:
        return None


class _Pool:
    """Logins at the router's address, in order: True works, False is refused."""

    def __init__(self, logins: list[bool]) -> None:
        self.logins = logins
        self.tries = 0

    async def drop(self, router_id: str) -> None:
        return None

    async def fresh(self, rec: RouterRecord) -> _Up:
        self.tries += 1
        if not self.logins.pop(0):
            raise TransportError("Connection refused")
        return _Up()


async def _gone(logins: list[bool]) -> tuple[bool, int]:
    pool = _Pool(logins)
    now = [0.0]

    async def sleep(seconds: float) -> None:
        now[0] += seconds

    gone = await wait_until_gone(
        pool,  # type: ignore[arg-type]
        REC,
        armed_at=0.0,
        clock=lambda: now[0],
        sleep=sleep,
        every_s=2.0,
        limit_s=20.0,
    )
    return gone, pool.tries


async def test_one_failed_login_is_not_gone() -> None:
    assert await _gone([False, True, False, False, False]) == (True, 5)


async def test_never_three_in_a_row_is_not_gone_by_the_limit() -> None:
    assert await _gone([False, True] * 10) == (False, 10)
