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
    profiles_dir: Path
    tools_dir: Path
    reflash_dir: Path

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
            profiles_dir=root / "profiles",
            tools_dir=root / "tools",
            reflash_dir=root / "reflash",
        )
        for folder in (
            d.root,
            d.keys_dir,
            d.audit_dir,
            d.updates_dir,
            d.logs_dir,
            d.profiles_dir,
            d.tools_dir,
            d.reflash_dir,
        ):
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


def resolve_data_root(
    env: Mapping[str, str] = os.environ,
    read_registry: Callable[[], str | None] = read_registry_data_dir,
) -> Path:
    """Env OPENWRTGUI_DATA, then the installer's registry value, then the per-user default."""
    explicit = env.get(ENV_DATA)
    if explicit:
        return Path(explicit)
    from_registry = read_registry()
    if from_registry:
        return Path(from_registry)
    return _default_root(env)


def resolve_data_dir(
    env: Mapping[str, str] = os.environ,
    read_registry: Callable[[], str | None] = read_registry_data_dir,
) -> DataDir:
    return DataDir.at(resolve_data_root(env, read_registry))


def simulator_data_dir(
    env: Mapping[str, str] = os.environ,
    read_registry: Callable[[], str | None] = read_registry_data_dir,
) -> DataDir:
    """A sibling of the real data folder (<data>-simulator), so simulated routers and keys stay out of it."""
    root = resolve_data_root(env, read_registry)
    return DataDir.at(root.with_name(f"{root.name}-simulator"))


def _windows_documents() -> Path | None:
    """The user's Documents folder as Windows knows it (it may be redirected, e.g. to OneDrive)."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    from uuid import UUID

    class _Guid(ctypes.Structure):
        _fields_ = [("data", ctypes.c_byte * 16)]

    folder = _Guid()
    folder.data[:] = UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}").bytes_le  # FOLDERID_Documents
    path = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined, unused-ignore]
    if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, wintypes.HANDLE(0), ctypes.byref(path)) != 0:
        return None
    try:
        return Path(path.value) if path.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)  # type: ignore[attr-defined, unused-ignore]


def documents_dir() -> Path:
    """Where RF recordings and captures go (inside it, OpenWrtGUI\\)."""
    return _windows_documents() or Path.home() / "Documents"


def web_dir(explicit: Path | None) -> Path | None:
    """The built UI: explicit path, the bundled copy when frozen, or frontend/dist in a checkout."""
    if explicit is not None:
        return explicit
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "openwrtgui" / "web"
    checkout = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return checkout if checkout.is_dir() else None
