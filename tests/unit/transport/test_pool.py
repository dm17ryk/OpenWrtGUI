from datetime import datetime, timedelta

import pytest

from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import KeyFileError, Transport, Unreachable
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.transport.pool import ConnectionPool


def _rec(router_id: str) -> RouterRecord:
    return RouterRecord(
        id=router_id, name=router_id, host="10.0.0.1", auth="key", added_at=datetime(2026, 11, 3)
    )


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 3, 12, 0)

    def __call__(self) -> datetime:
        return self.now


async def test_reuses_open_transport() -> None:
    made: list[str] = []

    async def factory(rec: RouterRecord) -> Transport:
        made.append(rec.id)
        return ReplayTransport({})

    pool = ConnectionPool(factory)
    a = await pool.get(_rec("ap2"))
    b = await pool.get(_rec("ap2"))
    assert a is b and made == ["ap2"]
    assert pool.health("ap2").online


async def test_unreachable_router_backs_off_and_reports_offline() -> None:
    clock = Clock()
    calls: list[datetime] = []

    async def factory(rec: RouterRecord) -> Transport:
        calls.append(clock.now)
        raise Unreachable("10.0.0.1:22: timed out")

    pool = ConnectionPool(factory, clock=clock)
    with pytest.raises(Unreachable):
        await pool.get(_rec("ap1"))
    health = pool.health("ap1")
    assert not health.online and health.error == "10.0.0.1:22: timed out"
    clock.now += timedelta(seconds=2)
    with pytest.raises(Unreachable) as exc:
        await pool.get(_rec("ap1"))
    assert len(calls) == 1
    assert exc.value.retry_at == datetime(2026, 11, 3, 12, 0, 5)
    clock.now += timedelta(seconds=10)
    with pytest.raises(Unreachable):
        await pool.get(_rec("ap1"))
    assert len(calls) == 2


async def test_backoff_caps_at_60_seconds() -> None:
    clock = Clock()

    async def factory(rec: RouterRecord) -> Transport:
        raise Unreachable("down")

    pool = ConnectionPool(factory, clock=clock)
    for _ in range(8):
        clock.now += timedelta(seconds=61)
        with pytest.raises(Unreachable):
            await pool.get(_rec("ap1"))
    with pytest.raises(Unreachable) as exc:
        await pool.get(_rec("ap1"))
    assert exc.value.retry_at is not None and exc.value.retry_at - clock.now == timedelta(seconds=60)


async def test_drop_closes_and_reconnects() -> None:
    made = 0

    async def factory(rec: RouterRecord) -> Transport:
        nonlocal made
        made += 1
        return ReplayTransport({})

    pool = ConnectionPool(factory)
    await pool.get(_rec("ap2"))
    await pool.drop("ap2")
    await pool.get(_rec("ap2"))
    assert made == 2
    await pool.close_all()


async def test_drop_forgets_the_backoff_so_a_re_added_router_connects_at_once() -> None:
    clock = Clock()
    attempts = 0

    async def factory(rec: RouterRecord) -> Transport:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KeyFileError(r"C:\home\.ssh\id_rsa", "No such file")
        return ReplayTransport({})

    pool = ConnectionPool(factory, clock=clock)
    with pytest.raises(KeyFileError):
        await pool.get(_rec("ap2"))
    assert "id_rsa" in (pool.health("ap2").error or "")
    await pool.drop("ap2")  # what the wizard does when the router is added again
    await pool.get(_rec("ap2"))
    assert attempts == 2 and pool.health("ap2").online


def test_write_lock_is_per_router() -> None:
    pool = ConnectionPool(lambda rec: ReplayTransport({}))  # type: ignore[arg-type, return-value]
    assert pool.write_lock("ap1") is pool.write_lock("ap1")
    assert pool.write_lock("ap1") is not pool.write_lock("ap2")
