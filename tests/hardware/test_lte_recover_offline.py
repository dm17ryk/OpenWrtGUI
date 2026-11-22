"""Offline: the LTE Recover window test makes a rung "not count" only after it settled, as real Recover waits
after each rung (2026-11-19 window: skipping the wait cut netifd's connect script off mid-setup, and AP2's
LTE stayed down until a router reboot)."""

from __future__ import annotations

from lte_window import gap_widths, parse_samples, wait_for_gap
from test_ap2_lte_recover import _not_settled_for


class _Recover:
    def __init__(self) -> None:
        self.waited = 0

    async def _wait_works(self, run: object) -> bool:
        self.waited += 1
        return True

    async def _works(self, run: object) -> bool:
        return True


async def test_a_rung_that_does_not_count_still_settles_first() -> None:
    recover = _Recover()
    _not_settled_for(recover, 2)  # type: ignore[arg-type]
    assert await recover._works(None) is False  # v1.3a I2: the check before a forced step says "not yet"
    answers = [await recover._wait_works(None) for _ in range(3)]
    assert answers == [False, False, True]
    assert recover.waited == 3  # every rung waited for LTE, as real Recover does
    assert await recover._works(None) is True  # past the forced steps, the real answer


def test_gap_widths_measure_each_idle_run_between_setups() -> None:
    """v1.3a final review I4: the window measures how long netifd's retries leave no setup running."""
    samples = [(0.0, 1), (0.25, 2), (0.5, 0), (0.75, 0), (1.0, 1), (1.25, 0), (1.5, 1), (1.75, 0)]
    assert gap_widths(samples) == [0.5, 0.25]  # the trailing idle run is not closed by a setup: not a gap
    assert gap_widths([(0.0, 0), (1.0, 0)]) == []


def test_parse_samples_reads_the_routers_loop() -> None:
    text = "123.45 1 0\n123.70 0 0\nbusybox: sleep: invalid number\n123.95 1 1\n"
    assert parse_samples(text) == [(123.45, 1, 0), (123.70, 0, 0), (123.95, 1, 1)]


async def test_wait_for_gap_returns_at_the_first_idle_read() -> None:
    """Final review I1: the test's own APN restore reloads lte, so it waits for a gap first."""
    answers = iter([False, False, True, False])
    reads = []

    async def idle() -> bool:
        reads.append(1)
        return next(answers)

    async def no_sleep(_: float) -> None:
        return None

    assert await wait_for_gap(idle, limit_s=10.0, step_s=0.25, sleep=no_sleep) is True
    assert len(reads) == 3


async def test_wait_for_gap_gives_up_at_its_limit() -> None:
    now = [0.0]

    async def busy() -> bool:
        return False

    async def tick(seconds: float) -> None:
        now[0] += seconds

    assert await wait_for_gap(busy, limit_s=2.0, step_s=0.5, sleep=tick, clock=lambda: now[0]) is False
    assert now[0] >= 2.0
