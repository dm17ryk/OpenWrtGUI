from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from openwrtgui import main
from openwrtgui.main import InstanceLock, Options, parse_args, run
from openwrtgui.paths import DataDir
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


@pytest.fixture
def _own_logging() -> Iterator[None]:
    """The root and asyncssh loggers as they were: an earlier `run` in this process left its app log handler
    on the root, and `_setup_logging` adds none while one is there."""
    root, ssh = logging.getLogger(), logging.getLogger("asyncssh")
    handlers, root_level, ssh_level = root.handlers[:], root.level, ssh.level
    root.handlers = [h for h in handlers if not isinstance(h, RotatingFileHandler)]
    try:
        yield
    finally:
        for h in root.handlers:
            if isinstance(h, RotatingFileHandler) and h not in handlers:
                h.close()
        root.handlers = handlers
        root.setLevel(root_level)
        ssh.setLevel(ssh_level)


@pytest.mark.usefixtures("_own_logging")
def test_the_app_log_never_records_router_commands(tmp_path: Path) -> None:
    """asyncssh logs every command it runs at INFO (`  Command: ...`); a command can carry a SIM PIN, an APN
    password or a Wi-Fi key. Its warnings still reach the app log."""
    data = DataDir.at(tmp_path / "data")
    main._setup_logging(data)
    (handler,) = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    ssh = logging.getLogger("asyncssh")
    ssh.info("  Command: %s", "uqmi -s -d /dev/cdc-wdm0 -t 5000 --verify-pin1 1234")
    ssh.warning("Connection lost to the router")
    logging.getLogger("openwrtgui").info("the app's own INFO lines stay")
    handler.flush()
    handler.close()
    text = (data.logs_dir / "app.log").read_text(encoding="utf-8")
    assert "--verify-pin1" not in text and "1234" not in text
    assert "WARNING asyncssh: Connection lost to the router" in text
    assert "the app's own INFO lines stay" in text
