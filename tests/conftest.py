"""Shared fixtures: replay transports built from the recorded AP2 output and the simulator overlays."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from openwrtgui.transport.fake import ReplayTransport, load_commands

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIM_DIR = FIXTURES / "sim"


@pytest.fixture
def ap2_transport() -> ReplayTransport:
    return ReplayTransport(load_commands(FIXTURES / "ap2" / "commands.json"))


@pytest.fixture
def sim_transport() -> Callable[[str], ReplayTransport]:
    from openwrtgui.simulator import sim_commands

    def make(router_id: str) -> ReplayTransport:
        return ReplayTransport(sim_commands(SIM_DIR, router_id))

    return make
