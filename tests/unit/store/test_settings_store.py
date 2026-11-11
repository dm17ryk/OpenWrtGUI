import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openwrtgui.store.settings import DEFAULT_PROCESSES, Settings, SettingsStore


def test_settings_defaults(tmp_path: Path) -> None:
    s = SettingsStore(tmp_path / "settings.json").load()
    assert s.theme == "system"
    assert s.update_channel == "stable"
    assert s.auto_check is True
    assert s.audit_retention_days == 90
    assert s.guard.lock_files == [r"D:\Essence_SC\wifi_ref\iperf_txsweep\voip.lock.own"]
    assert s.guard.processes == [
        "dima_night.py",
        "rh_soak.py",
        "overnight_wifi*",
        "txlab_*.py",
        "voip_chain.py",
        "mem04_bench.py",
    ]
    assert s.guard.router_ssids == ["OpenWrtB", "OpenWrtC"]
    assert s.guard.router_processes == []


OLD_DEFAULT = ["dima_night.py", "rh_soak.py", "overnight_wifi*", "txlab_*.py", "voip_chain.py"]  # v0.1-v0.5


def _saved(tmp_path: Path, processes: list[str]) -> Path:
    path = tmp_path / "settings.json"
    guard = {"processes": processes, "lock_files": ["C:\\\\x.lock"], "router_ssids": ["Run"]}
    path.write_text(json.dumps({"theme": "dark", "guard": guard}), encoding="utf-8")
    return path


def test_a_saved_old_default_watch_list_gains_the_new_default(tmp_path: Path) -> None:
    """A list saved as an earlier release shipped it (in any order) was never edited: it follows the default,
    so an install that saved any setting before 0.6.0 also watches mem04_bench.py (PR #49 review)."""
    path = _saved(tmp_path, list(reversed(OLD_DEFAULT)))
    before = path.read_text(encoding="utf-8")
    s = SettingsStore(path).load()
    assert s.guard.processes == list(DEFAULT_PROCESSES) and "mem04_bench.py" in s.guard.processes
    assert (s.theme, s.guard.lock_files, s.guard.router_ssids) == ("dark", ["C:\\\\x.lock"], ["Run"])
    assert path.read_text(encoding="utf-8") == before  # not rewritten on load; the next save writes it


def test_an_edited_watch_list_is_kept_as_saved(tmp_path: Path) -> None:
    for edited in ([*OLD_DEFAULT, "my_run.py"], OLD_DEFAULT[:-1], ["only_mine.py"], []):
        assert SettingsStore(_saved(tmp_path, edited)).load().guard.processes == edited


def test_save_and_load(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.save(store.load().model_copy(update={"theme": "dark", "audit_retention_days": 365}))
    s = SettingsStore(tmp_path / "settings.json").load()
    assert (s.theme, s.audit_retention_days) == ("dark", 365)


def test_invalid_theme_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"theme": "blue"})


def test_corrupt_settings_fall_back_to_defaults_and_keep_a_copy(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{oops", encoding="utf-8")
    assert SettingsStore(p).load().theme == "system"
    assert (tmp_path / "settings.json.bad").read_text(encoding="utf-8") == "{oops"


def test_known_keys_round_trip(tmp_path: Path) -> None:
    from openwrtgui.store.settings import KnownKey, Settings, SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    assert store.load().known_keys == []
    store.save(Settings(known_keys=[KnownKey(fingerprint="SHA256:abc", owner="dima_night")]))
    assert store.load().known_keys == [KnownKey(fingerprint="SHA256:abc", owner="dima_night")]
