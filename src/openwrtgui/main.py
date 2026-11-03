"""Launcher: one instance, local server on a random port, the window (or the browser)."""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO

import httpx
import uvicorn

from openwrtgui.app import create_app
from openwrtgui.context import AppContext, build_context
from openwrtgui.paths import DataDir, resolve_data_dir, web_dir
from openwrtgui.update.installer import launch_installer
from openwrtgui.version import APP_VERSION

log = logging.getLogger("openwrtgui")

ALREADY_RUNNING = "OpenWrtGUI is already running."
EXIT_SECOND_INSTANCE = 3
STARTUP_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Options:
    simulator: Path | None
    port: int | None
    token: str | None
    no_window: bool
    web_dir: Path | None
    data_dir: Path | None
    self_check: bool


def parse_args(argv: Sequence[str]) -> Options:
    ap = argparse.ArgumentParser(prog="OpenWrtGUI")
    ap.add_argument("--simulator", type=Path, help="serve the router simulator from this fixtures folder")
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--no-window", action="store_true", help="serve only; open nothing")
    ap.add_argument("--web-dir", type=Path)
    ap.add_argument("--data-dir", type=Path)
    ap.add_argument("--self-check", action="store_true", help="start, check /api/health and /, exit")
    a = ap.parse_args(list(argv))
    return Options(a.simulator, a.port, a.token, a.no_window, a.web_dir, a.data_dir, a.self_check)


class InstanceLock:
    """Exclusive lock on <data>/app.lock; entering returns False when another instance holds it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[bytes] | None = None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._file is None:
            return
        if sys.platform == "win32":
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._file.close()
        self._file = None


def _message_box(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "OpenWrtGUI", 0x40)
    else:
        print(text, file=sys.stderr)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _setup_logging(data: DataDir) -> None:
    handler = RotatingFileHandler(
        data.logs_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def _start_server(ctx: AppContext) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        create_app(ctx), host="127.0.0.1", port=ctx.port, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="openwrtgui-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("the local server did not start")
        time.sleep(0.05)
    return server, thread


def _self_check(port: int) -> int:
    base = f"http://127.0.0.1:{port}"
    try:
        health = httpx.get(f"{base}/api/health", timeout=10).json()
        index = httpx.get(f"{base}/", timeout=10)
    except httpx.HTTPError as exc:
        log.error("self-check failed: %s", exc)
        return 1
    ok = health.get("version") == APP_VERSION and index.status_code == 200 and '<div id="root">' in index.text
    log.info("self-check %s (version %s, index %s)", "passed" if ok else "failed", health, index.status_code)
    return 0 if ok else 1


def _wait_for_quit(ctx: AppContext, thread: threading.Thread) -> None:
    try:
        while not ctx.quit_event.is_set() and thread.is_alive():
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass


def _show_window(ctx: AppContext, url: str, thread: threading.Thread) -> None:
    try:
        import webview

        window = webview.create_window("OpenWrtGUI", url, width=1440, height=900, min_size=(375, 600))
        if window is None:
            raise RuntimeError("pywebview returned no window")

        def close_on_quit() -> None:
            _wait_for_quit(ctx, thread)
            window.destroy()

        threading.Thread(target=close_on_quit, daemon=True).start()
        webview.start(gui="edgechromium")
    except Exception:
        log.exception("the window could not open (WebView2 missing?); using the default browser")
        webbrowser.open(url)
        _wait_for_quit(ctx, thread)


def run(argv: Sequence[str] | None = None) -> int:
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    data = DataDir.at(opts.data_dir) if opts.data_dir else resolve_data_dir()
    with InstanceLock(data.root / "app.lock") as held:
        if not held:
            if not opts.no_window and not opts.self_check:
                _message_box(ALREADY_RUNNING)
            return EXIT_SECOND_INSTANCE
        _setup_logging(data)
        port = opts.port or _free_port()
        token = opts.token or secrets.token_urlsafe(32)
        install_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else None
        ctx = build_context(
            data,
            token=token,
            port=port,
            simulator=opts.simulator,
            web_dir=web_dir(opts.web_dir),
            install_dir=install_dir,
        )
        server, thread = _start_server(ctx)
        try:
            if opts.self_check:
                return _self_check(port)
            url = f"http://127.0.0.1:{port}/#token={token}"
            log.info("OpenWrtGUI %s serving on 127.0.0.1:%s (%s)", APP_VERSION, port, ctx.mode)
            if opts.no_window:
                _wait_for_quit(ctx, thread)
            else:
                _show_window(ctx, url, thread)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        if ctx.exit_command:
            log.info("starting the installer: %s", ctx.exit_command[0])
            launch_installer(ctx.exit_command)
        return 0
