"""system/backup.py listing: a router's archives by its own id, whatever its length (final review #1)."""

from __future__ import annotations

from pathlib import Path

from openwrtgui.system.backup import listing

LONG = "ap2-office-second-floor-lab-bench-rack-3"  # make_router_id slugifies names with no length cap


def test_a_long_router_id_lists_its_backups(tmp_path: Path) -> None:
    mine = tmp_path / f"{LONG}-20261109-120000.tar.gz"
    mine.write_bytes(b"\x1f\x8b")
    (tmp_path / "ap1-20261109-120000.tar.gz").write_bytes(b"\x1f\x8b")  # another router's name
    (tmp_path / f"{LONG}-20261109-120001.tar.gz.part").write_bytes(b"\x1f\x8b")  # still being written
    assert [b.name for b in listing(tmp_path, LONG)] == [mine.name]
