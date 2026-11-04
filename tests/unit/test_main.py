from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openwrtgui import main
from openwrtgui.main import InstanceLock, Options, parse_args, run
from openwrtgui.store import keys as keys_module

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"


@pytest.fixture(autouse=True)
def _no_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)


def test_parse_args_defaults() -> None:
    assert parse_args([]) == Options(None, None, None, False, None, None, False)


def test_parse_args_all_flags(tmp_path: Path) -> None:
    opts = parse_args(
        [
            "--simulator", str(SIM_DIR), "--port", "8765", "--token", "e2e", "--no-window",
            "--web-dir", str(tmp_path), "--data-dir", str(tmp_path / "d"), "--self-check",
        ]
    )  # fmt: skip
    assert opts == Options(SIM_DIR, 8765, "e2e", True, tmp_path, tmp_path / "d", True)


def test_self_check_passes_with_simulator(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    args = [
        "--self-check",
        "--simulator",
        str(SIM_DIR),
        "--web-dir",
        str(web),
        "--data-dir",
        str(tmp_path / "d"),
    ]
    assert run(args) == 0
    assert run(args) == 0  # the instance lock was released


def test_self_check_passes_without_console_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The windowed exe (console=False) runs with sys.stdout and sys.stderr set to None."""
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    args = [
        "--self-check", "--simulator", str(SIM_DIR), "--web-dir", str(web), "--data-dir", str(tmp_path / "d"),
    ]  # fmt: skip
    assert run(args) == 0


def test_simulator_never_uses_the_real_data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--simulator without --data-dir must not seed AP1/AP2 or fake host keys into the real data."""
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    real = tmp_path / "OpenWrtGUI data"
    monkeypatch.setenv("OPENWRTGUI_DATA", str(real))
    assert run(["--self-check", "--simulator", str(SIM_DIR), "--web-dir", str(web)]) == 0
    assert not (real / "routers.json").exists()
    assert (tmp_path / "OpenWrtGUI data-simulator" / "routers.json").is_file()


def test_self_check_fails_without_ui(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    args = [
        "--self-check",
        "--simulator",
        str(SIM_DIR),
        "--web-dir",
        str(empty),
        "--data-dir",
        str(tmp_path / "d"),
    ]
    assert run(args) == 1


def test_second_instance_returns_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "d"
    data.mkdir()
    shown: list[str] = []
    monkeypatch.setattr(main, "_message_box", shown.append)
    with InstanceLock(data / "app.lock") as held:
        assert held
        assert run(["--no-window", "--simulator", str(SIM_DIR), "--data-dir", str(data)]) == 3
        assert run(["--simulator", str(SIM_DIR), "--data-dir", str(data)]) == 3
    assert shown == ["OpenWrtGUI is already running."]
