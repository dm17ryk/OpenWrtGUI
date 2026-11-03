from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from openwrtgui.live import LiveHub
from openwrtgui.store.settings import SettingsStore
from openwrtgui.update.github import RELEASES_URL, fetch_releases, pick_release
from openwrtgui.update.installer import ChecksumMismatch, download_release, installer_command
from openwrtgui.update.service import Updater
from openwrtgui.update.versions import Version, parse_version

RELEASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "github" / "releases.json").read_text("utf-8")
)
PAYLOAD = b"MZ fake installer bytes"


def _handler(sums_ok: bool = True, status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(RELEASES_URL):
            if status != 200:
                return httpx.Response(status, json={"message": "API rate limit exceeded"})
            return httpx.Response(200, json=RELEASES)
        if url.endswith(".exe"):
            return httpx.Response(200, content=PAYLOAD)
        if url.endswith("SHA256SUMS.txt"):
            name = url.split("/")[-2].removeprefix("v")
            digest = hashlib.sha256(PAYLOAD if sums_ok else b"other").hexdigest()
            return httpx.Response(200, text=f"{digest}  OpenWrtGUI-Setup-{name}.exe\n")
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, follow_redirects=True)


def test_version_order() -> None:
    assert parse_version("v0.1.0-ci.5") < parse_version("0.1.0-ci.42") < parse_version("v0.1.0")
    assert parse_version("v0.1.0") < parse_version("v0.1.1-ci.1")
    assert parse_version("0.1.0-dev") < parse_version("0.1.0-ci.1")
    assert str(parse_version("v0.1.1-ci.7")) == "0.1.1-ci.7"
    with pytest.raises(ValueError):
        parse_version("nightly")


async def test_fetch_skips_releases_without_assets() -> None:
    async with _client(_handler()) as client:
        releases = await fetch_releases(client)
    assert [str(r.version) for r in releases] == ["0.1.1-ci.7", "0.1.0"]
    assert (
        releases[1].installer_name == "OpenWrtGUI-Setup-0.1.0.exe" and releases[1].installer_size == 48200000
    )


async def test_channels_pick() -> None:
    async with _client(_handler()) as client:
        releases = await fetch_releases(client)
    old = Version(0, 0, 9, None)
    assert str(pick_release(releases, "stable", old, None).version) == "0.1.0"  # type: ignore[union-attr]
    assert str(pick_release(releases, "prerelease", old, None).version) == "0.1.1-ci.7"  # type: ignore[union-attr]
    assert pick_release(releases, "stable", old, "0.1.0") is None
    assert pick_release(releases, "stable", Version(0, 1, 0, None), None) is None


def _updater(tmp_path: Path, transport: httpx.MockTransport, install_dir: Path | None = None) -> Updater:
    return Updater(
        settings=SettingsStore(tmp_path / "settings.json"),
        updates_dir=tmp_path / "updates",
        current=Version(0, 0, 9, None),
        client_factory=lambda: _client(transport),
        install_dir=install_dir,
        hub=LiveHub(),
    )


async def test_check_reports_rate_limit_without_raising(tmp_path: Path) -> None:
    status = await _updater(tmp_path, _handler(status=403)).check(force=True)
    assert status.error is not None and status.error.startswith("Couldn't check for updates")
    assert "403" in status.error and not status.available


async def test_check_reports_timeout_without_raising(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    status = await _updater(tmp_path, httpx.MockTransport(boom)).check(force=True)
    assert status.error is not None and "timed out" in status.error


async def test_check_offers_and_respects_daily_limit(tmp_path: Path) -> None:
    calls = 0
    inner = _handler()

    def count(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return inner.handle_request(request)

    updater = _updater(tmp_path, httpx.MockTransport(count))
    status = await updater.check()
    assert status.available and status.latest is not None and str(status.latest.version) == "0.1.0"
    assert status.can_install is False
    await updater.check()
    assert calls == 1
    store = SettingsStore(tmp_path / "settings.json")
    store.save(store.load().model_copy(update={"last_check": datetime.now() - timedelta(hours=25)}))
    await updater.check()
    assert calls == 2


async def test_checksum_mismatch_deletes_download(tmp_path: Path) -> None:
    async with _client(_handler(sums_ok=False)) as client:
        release = (await fetch_releases(client))[1]
        with pytest.raises(ChecksumMismatch):
            await download_release(client, release, tmp_path, lambda done, total: None)
    assert list(tmp_path.iterdir()) == []


async def test_keeps_previous_installer_only(tmp_path: Path) -> None:
    for old in ("0.0.8", "0.0.9"):
        (tmp_path / f"OpenWrtGUI-Setup-{old}.exe").write_bytes(b"old")
    progress: list[tuple[int, int]] = []
    async with _client(_handler()) as client:
        release = (await fetch_releases(client))[1]
        path = await download_release(client, release, tmp_path, lambda d, t: progress.append((d, t)))
    assert path.read_bytes() == PAYLOAD
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "OpenWrtGUI-Setup-0.0.9.exe",
        "OpenWrtGUI-Setup-0.1.0.exe",
    ]
    assert progress and progress[-1][0] == len(PAYLOAD)


async def test_install_returns_command_and_previous_installer(tmp_path: Path) -> None:
    updater = _updater(tmp_path, _handler(), install_dir=Path(r"C:\Essence_SC\apps\OpenWrtGUI"))
    (tmp_path / "updates").mkdir()
    (tmp_path / "updates" / "OpenWrtGUI-Setup-0.0.8.exe").write_bytes(b"old")
    await updater.check(force=True)
    cmd = await updater.install("0.1.0")
    assert cmd[0].endswith("OpenWrtGUI-Setup-0.1.0.exe") and cmd[1:4] == [
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/CLOSEAPPLICATIONS",
    ]
    previous = updater.previous_installer()
    assert previous is not None and previous.name == "OpenWrtGUI-Setup-0.0.8.exe"


async def test_install_refused_in_dev_build(tmp_path: Path) -> None:
    updater = _updater(tmp_path, _handler(), install_dir=None)
    await updater.check(force=True)
    with pytest.raises(ValueError, match="installed app"):
        await updater.install("0.1.0")


async def test_skip_hides_that_version(tmp_path: Path) -> None:
    updater = _updater(tmp_path, _handler())
    await updater.check(force=True)
    status = updater.skip("0.1.0")
    assert (
        not status.available and SettingsStore(tmp_path / "settings.json").load().skipped_version == "0.1.0"
    )


def test_installer_command_keeps_spaced_dir_as_one_argument() -> None:
    cmd = installer_command(
        Path(r"C:\data\updates\OpenWrtGUI-Setup-0.1.1.exe"), Path(r"C:\Essence_SC\apps\Open WrtGUI")
    )
    assert cmd[4] == r"/DIR=C:\Essence_SC\apps\Open WrtGUI" and cmd[-1] == "/RELAUNCH=1"
    assert len(cmd) == 6
