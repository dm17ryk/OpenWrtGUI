"""The update check the app runs at start-up and daily, and the install step."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from openwrtgui.live import LiveHub
from openwrtgui.store.settings import SettingsStore
from openwrtgui.update.github import Release, fetch_releases, pick_release
from openwrtgui.update.installer import ChecksumMismatch, download_release, installer_command, installers
from openwrtgui.update.versions import Version

log = logging.getLogger(__name__)

CHECK_EVERY = timedelta(hours=24)
DEV_ONLY = "Updates install only in the installed app."
IN_PROGRESS = "An update is already downloading."


class UpdateFailed(Exception):
    """Downloading or verifying the installer failed; nothing was run."""


class UpdateInProgress(Exception):
    """Another install request is still downloading."""


@dataclass(frozen=True)
class UpdateStatus:
    current: str
    channel: str
    latest: Release | None
    available: bool
    last_check: datetime | None
    error: str | None
    can_install: bool


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            return "GitHub refused the request (403, likely the hourly rate limit). Try again later."
        return f"GitHub answered {code}."
    return str(exc) or type(exc).__name__


class Updater:
    def __init__(
        self,
        *,
        settings: SettingsStore,
        updates_dir: Path,
        current: Version,
        client_factory: Callable[[], httpx.AsyncClient],
        install_dir: Path | None,
        hub: LiveHub,
    ) -> None:
        self._settings = settings
        self._updates_dir = updates_dir
        self._current = current
        self._client_factory = client_factory
        self._install_dir = install_dir
        self._installing = asyncio.Lock()
        self._hub = hub
        self._releases: list[Release] = []
        self._error: str | None = None

    def status(self) -> UpdateStatus:
        s = self._settings.load()
        latest = pick_release(self._releases, s.update_channel, self._current, s.skipped_version)
        return UpdateStatus(
            current=str(self._current),
            channel=s.update_channel,
            latest=latest,
            available=latest is not None,
            last_check=s.last_check,
            error=self._error,
            can_install=self._install_dir is not None,
        )

    async def check(self, force: bool = False) -> UpdateStatus:
        s = self._settings.load()
        due = s.last_check is None or datetime.now() - s.last_check.replace(tzinfo=None) >= CHECK_EVERY
        if not force and (not s.auto_check or not due):
            return self.status()
        try:
            async with self._client_factory() as client:
                self._releases = await fetch_releases(client)
            self._error = None
        except (httpx.HTTPError, ValueError) as exc:
            self._error = f"Couldn't check for updates: {_reason(exc)}"
            log.info(self._error)
        self._settings.save(self._settings.load().model_copy(update={"last_check": datetime.now()}))
        status = self.status()
        self._hub.publish({"type": "update", "status": status})
        return status

    async def install(self, version: str) -> list[str]:
        if self._install_dir is None:
            raise ValueError(DEV_ONLY)
        release = next((r for r in self._releases if str(r.version) == version), None)
        if release is None:
            raise ValueError(f"Version {version} is not on offer; check for updates first")

        def progress(done: int, total: int) -> None:
            self._hub.publish({"type": "update-progress", "version": version, "done": done, "total": total})

        if self._installing.locked():
            raise UpdateInProgress(IN_PROGRESS)
        async with self._installing:
            try:
                async with self._client_factory() as client:
                    path = await download_release(client, release, self._updates_dir, progress)
            except (ChecksumMismatch, httpx.HTTPError, OSError) as exc:
                log.warning("update %s failed: %s", version, exc)
                raise UpdateFailed(f"Couldn't download the update: {_reason(exc)}") from exc
        return installer_command(path, self._install_dir)

    def previous_installer(self) -> Path | None:
        older = [p for v, p in installers(self._updates_dir) if v < self._current]
        return older[-1] if older else None

    def reinstall_command(self) -> list[str] | None:
        previous = self.previous_installer()
        if previous is None or self._install_dir is None:
            return None
        return installer_command(previous, self._install_dir)

    def skip(self, version: str) -> UpdateStatus:
        self._settings.save(self._settings.load().model_copy(update={"skipped_version": version}))
        return self.status()
