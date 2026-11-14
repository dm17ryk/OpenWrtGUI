"""The simulator answers the LuCI page reads (v1.0a1 D7) from a per-router file map."""

from __future__ import annotations

from openwrtgui.luci_bridge.depends import files_command, listing_command, parse_ls
from openwrtgui.simfiles import SimFiles

FILES = {"/sbin/fw3": "executable", "/sys/class/leds": "directory", "/etc/x": "file"}


def test_listing_shows_what_the_map_has() -> None:
    sim = SimFiles(FILES)
    done = sim.answer(files_command(["/sbin/fw3", "/sbin/block", "/etc/x"]))
    assert done is not None and done.exit_status == 1  # one path is missing, as busybox ls says
    assert parse_ls(done.stdout) == {"/sbin/fw3": "executable", "/etc/x": "file"}


def test_directory_listing() -> None:
    sim = SimFiles({**FILES, "/sys/empty": "empty directory"})
    full = sim.answer(listing_command("/sys/class/leds"))
    empty = sim.answer(listing_command("/sys/empty"))
    assert full is not None and full.exit_status == 0 and full.stdout.strip()
    assert empty is not None and empty.exit_status == 0 and not empty.stdout.strip()
    assert sim.answer("ls -A /etc/config") is None  # not a path the map knows: others answer it
    assert sim.answer("uci -q show network") is None
