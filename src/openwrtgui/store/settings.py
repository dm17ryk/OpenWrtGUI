"""App settings (settings.json)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openwrtgui.store import write_atomic

log = logging.getLogger(__name__)

DEFAULT_LOCK_FILES = (r"D:\Essence_SC\wifi_ref\iperf_txsweep\voip.lock.own",)
DEFAULT_PROCESSES = ("dima_night.py", "rh_soak.py", "overnight_wifi*", "txlab_*.py", "voip_chain.py")


class GuardWatchList(BaseModel):
    """What Bench Guard watches for (spec section 6)."""

    model_config = ConfigDict(frozen=True)

    lock_files: list[str] = Field(default_factory=lambda: list(DEFAULT_LOCK_FILES))
    processes: list[str] = Field(default_factory=lambda: list(DEFAULT_PROCESSES))
    router_ssids: list[str] = Field(default_factory=lambda: ["OpenWrtB", "OpenWrtC"])
    router_processes: list[str] = Field(default_factory=list)


class KnownTable(BaseModel):
    """A known writer of an nft table, or of a chain inside fw4's table (spec 7.12, known writers)."""

    model_config = ConfigDict(frozen=True)

    match: str  # "<family> <table>" or "inet fw4 chain <name>"
    owner: str
    depends: str


DEFAULT_KNOWN_TABLES = (
    KnownTable(
        match="inet fw4 chain BENCHSIPGUARD",
        owner="dima_night",
        depends=(
            "dima_night expects BENCHSIPGUARD. Without it, SIP from the panels leaves the bench "
            "during soak runs."
        ),
    ),
    KnownTable(
        match="bridge voipdscp",
        owner="voip_chain",
        depends="VoIP chain runs expect RTP and SIP marked EF. Changing it changes their results.",
    ),
)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    theme: Literal["system", "light", "dark"] = "system"
    update_channel: Literal["stable", "prerelease"] = "stable"
    auto_check: bool = True
    skipped_version: str | None = None
    last_check: datetime | None = None
    audit_retention_days: Literal[30, 90, 365, 0] = 90
    guard: GuardWatchList = Field(default_factory=GuardWatchList)
    known_tables: list[KnownTable] = Field(default_factory=lambda: list(DEFAULT_KNOWN_TABLES))


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        text = self.path.read_text(encoding="utf-8")
        try:
            return Settings.model_validate_json(text)
        except ValidationError:
            bad = self.path.with_name(self.path.name + ".bad")
            bad.write_text(text, encoding="utf-8")
            log.warning("settings.json was unreadable; kept a copy in %s and used defaults", bad)
            return Settings()

    def save(self, settings: Settings) -> None:
        write_atomic(self.path, settings.model_dump_json(indent=2))
