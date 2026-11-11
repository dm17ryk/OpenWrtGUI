"""Which LuCI pages have a screen in the app (spec section 8); the rest open as fallback pages."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from openwrtgui.probe.luci_menu import SECTION_SEP, LuciPage

# LuCI page → the app screen that replaces it. Grows as native screens arrive (the roadmap's parity).
NATIVE: dict[str, str] = {
    "admin/network/wireless": "wifi",
    "admin/status/overview": "dashboard",
    "admin/network/network": "network",
    "admin/network/dhcp": "network",
    "admin/network/dns": "network",
    "admin/network/routes": "network",
    "admin/status/routes": "network",
    "admin/status/routesj": "network",  # the JSON variant; LuCI shows one of the two
    "admin/network/switch": "ports",
    "admin/network/firewall": "firewall",
    "admin/network/firewall/zones": "firewall",
    "admin/network/firewall/forwards": "firewall",
    "admin/network/firewall/rules": "firewall",
    "admin/network/firewall/snats": "firewall",
    "admin/network/firewall/ipsets": "firewall",
    "admin/network/firewall/custom": "firewall",
    "admin/status/nftables": "firewall",
    # v0.6b D11: the System screen; v0.6c D1: Administration and LEDs too (Mount points stays LuCI's: its page
    # needs block-mount, D8)
    "admin/system/admin": "system",
    "admin/system/admin/password": "system",
    "admin/system/admin/pwpolicy": "system",
    "admin/system/admin/dropbear": "system",
    "admin/system/admin/sshkeys": "system",
    "admin/system/admin/uhttpd": "system",
    "admin/system/admin/repokeys": "system",
    "admin/system/leds": "system",
    "admin/status/logs": "system",
    "admin/status/logs/syslog": "system",
    "admin/status/logs/dmesg": "system",
    "admin/status/processes": "system",
    "admin/status/realtime": "system",
    "admin/status/realtime/load": "system",
    "admin/status/realtime/bandwidth": "system",
    "admin/status/realtime/connections": "system",
    "admin/system/system": "system",
    "admin/system/startup": "system",
    "admin/system/crontab": "system",
    "admin/system/reboot": "system",
    "admin/system/flash": "system",
    "admin/network/diagnostics": "system",
}


@dataclass(frozen=True)
class PageView:
    path: str
    title: str
    package: str
    native: str | None
    section: str = ""
    label: str = ""  # unique on the router: "Status › Firewall (nftables)"


def _label(p: LuciPage) -> str:
    return f"{p.section}{SECTION_SEP}{p.title}" if p.section else p.title


def page_views(pages: Sequence[LuciPage]) -> list[PageView]:
    # LuCI hides one of two same-titled pages by its dependencies; the app lists both, so tell them apart.
    counts = Counter(_label(p) for p in pages)
    return [
        PageView(
            p.path,
            p.title,
            p.package,
            NATIVE.get(p.path),
            p.section,
            _label(p) if counts[_label(p)] == 1 else f"{_label(p)} ({p.path.rsplit('/', 1)[-1]})",
        )
        for p in pages
    ]


def fallback_pages(pages: Sequence[LuciPage]) -> list[LuciPage]:
    return [p for p in pages if p.path not in NATIVE]
