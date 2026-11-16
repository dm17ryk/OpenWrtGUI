"""The as-found check waits for the router to settle (AP2 window 2026-11-15: phy0-ap0's qdisc was still going
when fw_window compared, and gone a moment later)."""

from __future__ import annotations

from settle import settled


async def test_settled_reads_until_the_router_matches() -> None:
    reads = iter(["qdisc phy0-ap0", "qdisc phy0-ap0", "as found"])
    slept: list[float] = []

    async def read() -> str:
        return next(reads)

    async def sleep(s: float) -> None:
        slept.append(s)

    assert await settled(read, "as found", sleep=sleep) == "as found"
    assert slept == [1.0, 1.0]


async def test_settled_gives_up_with_the_last_read() -> None:
    calls: list[int] = []

    async def read() -> str:
        calls.append(1)
        return "still different"

    async def sleep(s: float) -> None:
        return None

    assert await settled(read, "as found", tries=3, sleep=sleep) == "still different"
    assert len(calls) == 3
