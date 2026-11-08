"""tools/mini_image.py: a pure-Python squashfs writer and the two mini sysupgrade images the tests use."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

from PySquashfsImage import SquashFsImage

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "mini_image.py"
FIXTURES = ROOT / "tests" / "fixtures" / "images"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mini_image", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mini_image"] = module
    spec.loader.exec_module(module)
    return module


mini = _load()


def test_squashfs_round_trip() -> None:
    raw = mini.build_squashfs(
        {"/a/b.txt": b"hello", "/a/link": mini.Link("b.txt"), "/c/d/e": b"x" * 300_000},
        modes={"/a/b.txt": 0o755},
    )
    image = SquashFsImage(io.BytesIO(raw))
    b = image.select("/a/b.txt")
    assert b.read_bytes() == b"hello"
    assert b.mode & 0o777 == 0o755
    assert image.select("/a/link").readlink() == "b.txt"
    assert image.select("/c/d/e").read_bytes() == b"x" * 300_000
    assert sorted(e.path for e in image if e.path != "/") == [
        "/a",
        "/a/b.txt",
        "/a/link",
        "/c",
        "/c/d",
        "/c/d/e",
    ]


def test_many_entries_in_one_directory() -> None:
    entries = {f"/bin/p{i:03}": bytes([i % 256]) * 8 for i in range(300)}
    image = SquashFsImage(io.BytesIO(mini.build_squashfs(entries)))
    assert len([e for e in image if e.path.startswith("/bin/")]) == 300
    assert image.select("/bin/p299").read_bytes() == bytes([299 % 256]) * 8


def test_mini_images_are_current() -> None:
    for revision in ("r35692-b8bffeefdf", "r35700-0c0ffee000"):
        name = f"mini-{revision[:6]}.bin"
        built = mini.build_sysupgrade(
            mini.mini_root(revision), kernel=b"K" * 4096, metadata=mini.metadata(revision)
        )
        assert (FIXTURES / name).read_bytes() == built, (
            f"run: uv run python tools/mini_image.py ({name} is stale)"
        )
