"""On AP2's own recordings, the depends rules hide exactly what LuCI hides on the bench image (v1.0a1 D6)."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.images.apkdb import parse_apk_installed
from openwrtgui.luci_bridge.depends import Facts, fs_paths, uci_configs, usable_groups, why_hidden
from openwrtgui.probe import commands as c
from openwrtgui.probe.describe import _json_blocks
from openwrtgui.probe.luci_menu import parse_acl, parse_menu
from openwrtgui.uci import parse_uci_show

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
COMMANDS = json.loads((FIXTURES / "commands.json").read_text("utf-8"))
DISCOVERY = json.loads((FIXTURES / "discovery.json").read_text("utf-8"))
UCI = json.loads((FIXTURES / "wifi_parked.json").read_text("utf-8"))["uci show"]["stdout"]
PAGES = parse_menu(_json_blocks(COMMANDS[c.LUCI_MENU]["stdout"]))


def _facts() -> Facts:
    owned = {
        "/" + f.lstrip("/")
        for p in parse_apk_installed(DISCOVERY["cat /lib/apk/db/installed"]["stdout"])
        for f in p.files
    }
    files = {p: "executable" for p in fs_paths(PAGES) if p in owned}
    files["/sys/class/leds"] = "directory"  # sysfs: no package owns it; AP2's LEDs tab lists its LEDs
    shown = parse_uci_show(UCI)
    uci = {cfg: {k: v for k, v in shown.items() if k.split(".", 1)[0] == cfg} for cfg in uci_configs(PAGES)}
    acl = usable_groups(parse_acl(_json_blocks(COMMANDS[c.LUCI_ACL]["stdout"])))
    return Facts(files, {k: v for k, v in uci.items() if v}, acl)


def test_ap2_hides_what_luci_hides_on_the_bench_image() -> None:
    facts = _facts()
    hidden = {p.path for p in PAGES if why_hidden(p, facts) is not None}
    assert hidden == {
        "admin/network/firewall/custom",
        "admin/network/switch-vlan",
        "admin/status/iptables",
        "admin/status/routes",
        "admin/system/mounts",
    }
