"""Where the app keeps its data and finds its web UI."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_DATA = "OPENWRTGUI_DATA"
REGISTRY_KEY = r"Software\OpenWrtGUI"
REGISTRY_VALUE = "DataDir"


@dataclass(frozen=True)
class DataDir:
    root: Path
    routers_file: Path
    settings_file: Path
    known_hosts_file: Path
    keys_dir: Path
    audit_dir: Path
    updates_dir: Path
    logs_dir: Path

    @classmethod
    def at(cls, root: Path) -> DataDir:
        d = cls(
            root=root,
            routers_file=root / "routers.json",
            settings_file=root / "settings.json",
            known_hosts_file=root / "known_hosts",
            keys_dir=root / "keys",
            audit_dir=root / "audit",
            updates_dir=root / "updates",
            logs_dir=root / "logs",
        )
        for folder in (d.root, d.keys_dir, d.audit_dir, d.updates_dir, d.logs_dir):
            folder.mkdir(parents=True, exist_ok=True)
        return d


def read_registry_data_dir() -> str | None:
    """The data folder the installer recorded under HKCU, if any."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE)
    except OSError:
        return None
    return str(value) if value else None


def _default_root(env: Mapping[str, str]) -> Path:
    local = env.get("LOCALAPPDATA")
    if local:
        return Path(local) / "OpenWrtGUI"
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local" / "OpenWrtGUI"
    return Path.home() / ".local" / "share" / "openwrtgui"


def resolve_data_dir(
    env: Mapping[str, str] = os.environ,
    read_registry: Callable[[], str | None] = read_registry_data_dir,
) -> DataDir:
    """Env OPENWRTGUI_DATA, then the installer's registry value, then the per-user default."""
    explicit = env.get(ENV_DATA)
    if explicit:
        return DataDir.at(Path(explicit))
    from_registry = read_registry()
    if from_registry:
        return DataDir.at(Path(from_registry))
    return DataDir.at(_default_root(env))


def web_dir(explicit: Path | None) -> Path | None:
    """The built UI: explicit path, the bundled copy when frozen, or frontend/dist in a checkout."""
    if explicit is not None:
        return explicit
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "openwrtgui" / "web"
    checkout = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return checkout if checkout.is_dir() else None
