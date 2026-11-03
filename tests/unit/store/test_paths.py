from pathlib import Path

from openwrtgui.paths import DataDir, resolve_data_dir


def test_env_wins(tmp_path: Path) -> None:
    d = resolve_data_dir(env={"OPENWRTGUI_DATA": str(tmp_path / "x")}, read_registry=lambda: "C:/nope")
    assert d.root == tmp_path / "x"
    assert d.keys_dir.is_dir() and d.audit_dir.is_dir()


def test_registry_used_when_no_env(tmp_path: Path) -> None:
    d = resolve_data_dir(env={}, read_registry=lambda: str(tmp_path / "reg"))
    assert d.root == tmp_path / "reg"


def test_default_under_localappdata(tmp_path: Path) -> None:
    d = resolve_data_dir(env={"LOCALAPPDATA": str(tmp_path)}, read_registry=lambda: None)
    assert d.root == tmp_path / "OpenWrtGUI"


def test_data_dir_with_spaces_and_unicode(tmp_path: Path) -> None:
    root = tmp_path / "OneDrive - Essence Security" / "данные OpenWrtGUI"
    d = DataDir.at(root)
    assert d.updates_dir.is_dir()
    assert d.logs_dir.is_dir()
    assert d.routers_file.parent == root
    assert d.known_hosts_file == root / "known_hosts"
