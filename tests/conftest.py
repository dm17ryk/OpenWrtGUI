"""Shared fixtures: replay transports built from the recorded AP2 output and the simulator overlays."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from openwrtgui.transport.fake import ReplayTransport, load_commands

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIM_DIR = FIXTURES / "sim"


def pytest_addoption(parser: pytest.Parser) -> None:
    # Registered here, not in tests/hardware/conftest.py: pytest reads options only from start-up conftests.
    group = parser.getgroup("hardware", "tests on a real router (pytest -m hardware)")
    group.addoption("--router", default="192.168.1.2", help="router address (default AP2, 192.168.1.2)")
    group.addoption("--identity", type=Path, help="an SSH private key the router accepts")
    group.addoption(
        "--known-hosts",
        type=Path,
        default=Path.home() / ".ssh" / "known_hosts",
        help="known_hosts that already has the router's host key (never pinned by the tests)",
    )
    group.addoption(
        "--allow-other", action="store_true", help="allow a router other than 192.168.1.2 (reads only)"
    )
    group.addoption("--allow-writes", action="store_true", help="allow tests that change AP2 and restore it")
    group.addoption("--txctl-told", action="store_true", help="the txctl session gave its OK for this window")
    group.addoption(
        "--allow-flash",
        action="store_true",
        help="allow the test that flashes AP2 (the owner's explicit OK: AP2 reboots, about 3 minutes away)",
    )
    group.addoption(
        "--allow-reboot",
        action="store_true",
        help="allow the test that reboots AP2 (the owner's own OK for it: AP2 is away about 90 s)",
    )
    group.addoption(
        "--adb-station", help="adb serial of the phone that joins the test SSID (Wi-Fi faults on air, O16)"
    )


@pytest.fixture
def ap2_transport() -> ReplayTransport:
    return ReplayTransport(load_commands(FIXTURES / "ap2" / "commands.json"))


@pytest.fixture
def sim_transport() -> Callable[[str], ReplayTransport]:
    from openwrtgui.simulator import sim_commands

    def make(router_id: str) -> ReplayTransport:
        return ReplayTransport(sim_commands(SIM_DIR, router_id))

    return make
