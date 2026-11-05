"""Which LuCI pages have a screen in the app (spec section 8); the rest open as fallback pages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from openwrtgui.probe.luci_menu import LuciPage

# LuCI page → the app screen that replaces it. Grows as native screens arrive (the roadmap's parity).
NATIVE: dict[str, str] = {
    "admin/network/wireless": "wifi",
    "admin/status/overview": "dashboard",
}


@dataclass(frozen=True)
class PageView:
    path: str
    title: str
    package: str
    native: str | None


def page_views(pages: Sequence[LuciPage]) -> list[PageView]:
    return [PageView(p.path, p.title, p.package, NATIVE.get(p.path)) for p in pages]


def fallback_pages(pages: Sequence[LuciPage]) -> list[LuciPage]:
    return [p for p in pages if p.path not in NATIVE]
