"""netifd values of the wrong type (v0.6a minor #24, v1.0c Task 10): shown as unknown, never a 500."""

from __future__ import annotations

import json
from datetime import datetime

from openwrtgui.lte import commands as c
from openwrtgui.lte.state import read_lte
from openwrtgui.transport.base import CommandResult

NOW = datetime(2026, 11, 16, 9, 0)


class Netifd:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = {command: json.dumps(value) for command, value in answers.items()}

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return CommandResult(command, self.answers.get(command, ""), "", 0)


async def test_netifd_values_of_the_wrong_type_show_as_unknown() -> None:
    t = Netifd(
        {
            c.iface_status("lte"): {"up": "yes", "pending": 0, "uptime": True, "l3_device": "wwan0"},
            c.device_status("wwan0"): {"statistics": {"rx_bytes": "12", "tx_bytes": 34}},
        }
    )
    state, _ = await read_lte(t, router_id="ap2", qmi=("lte", None), at_port=None, now=NOW)  # type: ignore[arg-type]
    assert (state.up, state.pending, state.uptime_s) == (None, None, None)
    assert (state.rx_bytes, state.tx_bytes) == (None, 34)


async def test_netifd_values_of_the_right_type_are_kept() -> None:
    t = Netifd(
        {
            c.iface_status("lte"): {"up": True, "pending": False, "uptime": 120, "l3_device": "wwan0"},
            c.device_status("wwan0"): {"statistics": {"rx_bytes": 12, "tx_bytes": 34}},
        }
    )
    state, _ = await read_lte(t, router_id="ap2", qmi=("lte", None), at_port=None, now=NOW)  # type: ignore[arg-type]
    values = (state.up, state.pending, state.uptime_s, state.rx_bytes, state.tx_bytes)
    assert values == (True, False, 120, 12, 34)
