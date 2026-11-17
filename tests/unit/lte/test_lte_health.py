"""When LTE works (spec 4.1): the interface is up, its status has a valid packet-data handle, and lte_4 has
an address."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from openwrtgui.lte.state import LteState, handle_ok, lte_works

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"up": True, "data": {"pdh_4": "90215808"}}, True),
        ({"up": True, "data": {"pdh_4": "0xffffffff"}}, False),
        ({"up": True, "data": {"pdh_4": "0xFFFFFFFF"}}, False),
        ({"up": True, "data": {"pdh_4": "4294967295"}}, False),
        ({"up": True}, False),
        ({"up": True, "data": {"cid_4": "11"}}, False),
        ({"up": True, "data": "garbled"}, False),
        ({"up": False, "data": {"pdh_4": "90215808"}}, None),
        (None, None),
    ],
)
def test_handle_ok(session: dict[str, Any] | None, expected: bool | None) -> None:
    assert handle_ok(session) is expected


def _state(**kw: Any) -> LteState:
    return LteState(router_id="ap2", read_at=NOW, available=True, **kw)


@pytest.mark.parametrize(
    ("up", "handle", "ipv4", "works"),
    [
        (True, True, "10.64.12.7", True),
        (False, True, "10.64.12.7", False),
        (None, True, "10.64.12.7", False),
        (True, False, "10.64.12.7", False),
        (True, None, "10.64.12.7", False),
        (True, True, None, False),
        (True, True, "", False),
    ],
)
def test_works_needs_up_handle_and_address(
    up: bool | None, handle: bool | None, ipv4: str | None, works: bool
) -> None:
    assert lte_works(_state(up=up, data_handle=handle, ipv4=ipv4)) is works
