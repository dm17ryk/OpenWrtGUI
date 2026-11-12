"""LuCI pages with a native screen (spec section 8): v0.7 adds Status › Channel analysis."""

from __future__ import annotations

from openwrtgui.luci_bridge.pages import NATIVE


def test_channel_analysis_is_native() -> None:
    assert NATIVE["admin/status/channel_analysis"] == "rf"
