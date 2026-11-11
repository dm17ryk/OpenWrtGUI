from pathlib import Path

import pytest
from pydantic import ValidationError

from openwrtgui.store.settings import Settings, SettingsStore


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
