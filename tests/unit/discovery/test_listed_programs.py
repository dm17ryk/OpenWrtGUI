"""Discovery's program check (v1.0c Task 5, #17): the custom programs a router has, read in two commands, are
exactly the ones the Discovery page lists."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.state import listed_programs, read_discovery
from openwrtgui.images.profile import Profile, build_profile
from openwrtgui.probe.describe import describe_router
from openwrtgui.transport.fake import ReplayTransport

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 16, 9, 0)


def _mini() -> Profile:
    return build_profile(MINI.read_bytes(), "mini-r35692.bin", NOW)


@pytest.mark.parametrize("router_id", ["ap1", "ap2", "ap3", "ap4"])
@pytest.mark.parametrize("with_profile", [False, True])
async def test_listed_programs_match_the_discovery_state(
    sim_transport: Callable[[str], ReplayTransport], router_id: str, with_profile: bool
) -> None:
    profile = _mini() if with_profile else None
    t = sim_transport(router_id)
    identity = (await describe_router(t)).identity
    state = await read_discovery(t, router_id=router_id, identity=identity, profile=profile, now=NOW)
    listed = {p.path for row in state.custom for p in row.programs} | {p.path for p in state.programs}
    assert await listed_programs(sim_transport(router_id), profile) == listed


async def test_the_check_reads_only_the_overlay_and_the_packages(
    sim_transport: Callable[[str], ReplayTransport],
) -> None:
    t = sim_transport("ap1")  # the plain recording has no apk database: opkg's status is the fallback
    found = await listed_programs(t, _mini())
    assert "/usr/bin/dwr921-at-probe" in found
    assert t.calls == [cmd.OVERLAY_LS, cmd.APK_DB, cmd.OPKG_STATUS]
