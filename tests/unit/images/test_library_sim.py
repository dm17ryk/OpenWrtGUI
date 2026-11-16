"""The simulator's GitHub stand-in and the image library in the app context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from openwrtgui.context import AppContext, build_context
from openwrtgui.paths import DataDir
from openwrtgui.simulator import sim_http_client
from openwrtgui.store import keys as keys_module

FIX = Path(__file__).resolve().parents[2] / "fixtures"
SIM_DIR = FIX / "sim"
TOKEN, PORT = "test-token", 8765
MINI = (FIX / "images" / "mini-r35692.bin").read_bytes()
UPDATER_URL = "https://api.github.com/repos/dm17ryk/OpenWrtGUI/releases"
LIBRARY_URL = "https://api.github.com/repos/dm17ryk/openwrt/releases"
DOWNLOAD = "https://github.com/dm17ryk/openwrt/releases/download/sim/"


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    yield build_context(
        DataDir.at(tmp_path / "data"), token=TOKEN, port=PORT, simulator=SIM_DIR, web_dir=None
    )


def test_the_sim_profiles_describe_the_mini_image() -> None:
    doc = json.loads((FIX / "github" / "openwrt-sim-profiles.json").read_text("utf-8"))
    profile = doc["profiles"]["dlink_dwr-921-c3-uboot"]
    (image,) = profile["images"]
    assert image["sha256"] == hashlib.sha256(MINI).hexdigest()
    assert image["size"] == len(MINI)
    assert profile["supported_devices"] == ["dlink,dwr-921-c3-uboot"]
    assert doc["version_code"] == "r35692-b8bffeefdf"


async def test_the_stand_in_keeps_the_updater_releases() -> None:
    expected = (FIX / "github" / "releases.json").read_bytes()
    async with sim_http_client(SIM_DIR) as client:
        updater = await client.get(UPDATER_URL)
        library = await client.get(LIBRARY_URL)
        profiles = await client.get(DOWNLOAD + "profiles.json")
        image = await client.get(DOWNLOAD + "mini-r35692.bin")
        other = await client.get(DOWNLOAD + "nothing.bin")
        elsewhere = await client.get("https://api.github.com/repos/dm17ryk/other/releases")
    assert updater.json() == json.loads(expected)
    assert [r["tag_name"] for r in library.json()] == ["sim"]
    assert profiles.status_code == 200 and profiles.json()["target"] == "ramips/mt7620"
    assert image.content == MINI
    assert other.status_code == 404
    assert elsewhere.status_code == 404


async def test_the_sim_library_offers_and_downloads_the_mini_image(ctx: AppContext) -> None:
    read = await ctx.library.read()
    assert [e.image_name for e in read.entries] == ["mini-r35692.bin"]
    p = await ctx.library.download(read.entries[0].sha256)
    assert p.key.label == "dlink,dwr-921-c3-uboot r35692-b8bffeefdf"
