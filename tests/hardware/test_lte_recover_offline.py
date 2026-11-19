"""Offline: the LTE Recover window test makes a rung "not count" only after it settled, as real Recover waits
after each rung (2026-11-19 window: skipping the wait cut netifd's connect script off mid-setup, and AP2's
LTE stayed down until a router reboot)."""

from __future__ import annotations

from test_ap2_lte_recover import _not_settled_for


class _Recover:
    def __init__(self) -> None:
        self.waited = 0

    async def _wait_works(self, run: object) -> bool:
        self.waited += 1
        return True


async def test_a_rung_that_does_not_count_still_settles_first() -> None:
    recover = _Recover()
    _not_settled_for(recover, 2)  # type: ignore[arg-type]
    answers = [await recover._wait_works(None) for _ in range(3)]
    assert answers == [False, False, True]
    assert recover.waited == 3  # every rung waited for LTE, as real Recover does
