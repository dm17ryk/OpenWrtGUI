"""Download an installer, check it against SHA256SUMS.txt, and start it silently."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx

from openwrtgui.update.github import Release
from openwrtgui.update.versions import Version, parse_version

PREFIX = "OpenWrtGUI-Setup-"


class ChecksumMismatch(Exception):
    """The downloaded installer is not the file the release lists."""


def installer_version(path: Path) -> Version | None:
    if not path.name.startswith(PREFIX) or path.suffix != ".exe":
        return None
    try:
        return parse_version(path.stem.removeprefix(PREFIX))
    except ValueError:
        return None


def installers(updates_dir: Path) -> list[tuple[Version, Path]]:
    found = [(v, p) for p in updates_dir.glob(f"{PREFIX}*.exe") if (v := installer_version(p)) is not None]
    return sorted(found, key=lambda item: item[0])


def _expected_hash(sums: str, name: str) -> str | None:
    for line in sums.splitlines():
        digest, _, file_name = line.strip().partition("  ")
        if file_name.lstrip("*") == name:
            return digest.lower()
    return None


async def download_release(
    client: httpx.AsyncClient,
    release: Release,
    updates_dir: Path,
    on_progress: Callable[[int, int], None],
) -> Path:
    updates_dir.mkdir(parents=True, exist_ok=True)
    sums = (await client.get(release.sums_url, timeout=30.0)).raise_for_status().text
    expected = _expected_hash(sums, release.installer_name)
    target = updates_dir / release.installer_name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done = 0
    try:
        async with client.stream("GET", release.installer_url, timeout=60.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", release.installer_size or 0))
            with part.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    on_progress(done, total)
    except BaseException:
        part.unlink(missing_ok=True)  # a cut download never lingers, let alone runs
        raise
    if expected is None or digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise ChecksumMismatch(f"{release.installer_name} does not match {release.sums_url}")
    part.replace(target)
    for _, old in installers(updates_dir)[:-2]:
        old.unlink(missing_ok=True)
    return target


def installer_command(installer: Path, install_dir: Path) -> list[str]:
    return [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/CLOSEAPPLICATIONS",
        f"/DIR={install_dir}",
        "/RELAUNCH=1",
    ]


def launch_installer(cmd: list[str]) -> None:
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(cmd, start_new_session=True, close_fds=True)
