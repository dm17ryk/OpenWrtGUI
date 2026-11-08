"""AP2 image windows (O17): the firmware check, an upload and validate in /tmp/owg, and a flash of the same
bench image keeping settings.

OWG_TEST_IMAGE=<the bench sysupgrade .bin> uv run pytest -m hardware tests/hardware/test_ap2_images.py \
    --router 192.168.1.2 --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved and the txctl session was told of. The first test writes only
/tmp/owg (RAM) and removes it. The flash test also needs --allow-flash, the owner's explicit OK for a flash:
AP2 reboots and is away about 3 minutes, and a failed flash needs his U-Boot recovery. The `fw_window` fixture
checks afterwards that the firewall, nft tables, qdiscs, /tmp/owg, switch ports and parked radio are as found.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from conftest import AP2, FwWindow
from openwrtgui.discovery import commands as dc
from openwrtgui.discovery.checklist import ChecklistStore
from openwrtgui.discovery.copy import CopyRequest
from openwrtgui.discovery.service import DiscoveryService
from openwrtgui.discovery.tools import ToolStore
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.flash.service import FlashJob, FlashService
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.images.profile import Profile
from openwrtgui.images.store import ProfileStore
from openwrtgui.probe.commands import RELEASE
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList, SettingsStore
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

ID = "ap2"
FLASH_TIMEOUT_S = 12 * 60


@dataclass
class ImagesWindow:
    discovery: DiscoveryService
    flash: FlashService
    profile: Profile
    w: FwWindow


@pytest.fixture
async def images_window(fw_window: FwWindow, tmp_path: Path) -> AsyncIterator[ImagesWindow]:
    image = os.environ.get("OWG_TEST_IMAGE")
    if not image:
        pytest.skip("set OWG_TEST_IMAGE to the bench sysupgrade image")
    profiles = ProfileStore(tmp_path / "images")
    profile = profiles.import_image(Path(image).read_bytes(), Path(image).name, datetime.now())
    routers = RouterStore(tmp_path / "images-routers.json")
    routers.upsert(RouterRecord(id=ID, name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    audit = AuditLog(tmp_path / "images-audit")
    discovery = DiscoveryService(
        pool=fw_window.pool,
        routers=routers,
        guard=guard,
        audit=audit,
        settings=SettingsStore(tmp_path / "images-settings.json"),
        descriptions={},
        profiles=profiles,
        checklists=ChecklistStore(tmp_path / "reflash"),
        tools=ToolStore(tmp_path / "tools"),
    )
    flash = FlashService(
        pool=fw_window.pool,
        routers=routers,
        guard=guard,
        audit=audit,
        profiles=profiles,
        discovery=discovery,
        net=fw_window.net,
    )
    yield ImagesWindow(discovery=discovery, flash=flash, profile=profile, w=fw_window)


def _request(profile: Profile) -> FlashRequest:
    return FlashRequest(board=profile.key.board, revision=profile.key.revision, sha256=profile.key.sha256)


async def _read(w: FwWindow, *commands: str) -> list[str]:
    t: SshTransport = await w.connect()
    try:
        return [(await t.run(c)).stdout for c in commands]
    finally:
        await t.close()


def _mem(meminfo: str) -> str:
    return next((ln for ln in meminfo.splitlines() if ln.startswith("MemAvailable:")), "MemAvailable: ?")


async def test_firmware_check_upload_and_validate(images_window: ImagesWindow) -> None:
    iw = images_window
    overlay, meminfo = await _read(iw.w, dc.OVERLAY_LS, dc.MEMINFO)
    check = await iw.discovery.check_firmware(ID)
    print(f"\nfirmware check: {check.detail} (read {check.read_s} s)")
    req = _request(iw.profile)
    plan = await iw.flash.plan(ID, req)
    print("\n".join(plan.lines), *plan.warnings, sep="\n")
    started = time.monotonic()
    result = await iw.flash.check_only(ID, req, plan.digest)
    print(f"check_only: {result.detail} ({time.monotonic() - started:.1f} s)")
    assert result.ok, result.detail
    state = await iw.discovery.state(ID)
    print("overlay added:", [e.path for e in state.overlay.added])
    print("overlay changed:", [e.path for e in state.overlay.replaced])
    print("overlay deleted:", list(state.overlay.deleted))
    print("packages added:", [p.name for p in state.packages.added])
    assert state.overlay.unreadable == 0
    overlay_after, meminfo_after, owg = await _read(
        iw.w, dc.OVERLAY_LS, dc.MEMINFO, "test -e /tmp/owg && echo present"
    )
    print(f"before: {_mem(meminfo)}; after: {_mem(meminfo_after)}")
    assert owg.strip() == "", "/tmp/owg is still there"
    assert overlay_after == overlay, "the overlay changed"


async def _wait(flash: FlashService) -> FlashJob:
    started = time.monotonic()
    seen = ""
    while time.monotonic() - started < FLASH_TIMEOUT_S:
        job = flash.job(ID)
        if job is not None and job.phase != seen:
            seen = job.phase
            print(f"{time.monotonic() - started:6.1f} s  {job.phase}  {job.sent}/{job.total}")
        if job is not None and job.phase in ("done", "failed"):
            return job
        await asyncio.sleep(1)
    raise AssertionError(f"the flash did not end within {FLASH_TIMEOUT_S} s: {flash.job(ID)}")


async def test_flash_same_image_keep_settings(
    images_window: ImagesWindow, request: pytest.FixtureRequest
) -> None:
    if not request.config.getoption("--allow-flash"):
        pytest.skip("flashing AP2 needs --allow-flash (the owner's explicit OK for this window)")
    iw = images_window
    uci, release = await _read(iw.w, "uci show", RELEASE)
    req = _request(iw.profile)
    assert f"DISTRIB_REVISION='{req.revision}'" in release, "AP2 must run the bench image before the flash"
    plan = await iw.flash.plan(ID, req)
    print("\n" + "\n".join(plan.lines), *plan.warnings, sep="\n")
    await iw.flash.start(ID, req, plan.digest)
    job = await _wait(iw.flash)
    assert job.phase == "done", job.error
    print(job.detail)
    # the same host key: the pool reconnected with the pinned key, and so does this read
    uci_after, release_after = await _read(iw.w, "uci show", RELEASE)
    assert release_after == release
    assert uci_after == uci, "a config changed"
    check = await iw.discovery.check_firmware(ID)
    print(f"firmware check after: {check.detail}")
    assert check.matches
    checklist = iw.discovery.checklists.latest(ID)
    assert checklist is not None, "no reflash checklist was saved before the flash"
    restorable = [f.path for f in checklist.lost if f.kind == "link" or f.data is not None]
    print("lost:", [f.path for f in checklist.lost], "restorable:", restorable)
    if restorable:
        copy = CopyRequest(paths=tuple(restorable), target=ID, from_checklist=checklist.stamp)
        copy_plan = await iw.discovery.plan_copy(ID, copy)
        result = await iw.discovery.apply_copy(ID, copy, copy_plan.digest)
        assert result.applied and result.verified, [(c.name, c.detail) for c in result.checks]
