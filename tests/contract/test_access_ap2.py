"""AP2's recorded Access, LED and mount reads (tests/fixtures/ap2/access.json, 2026-11-10) against the v0.6c
parsers. The recording found: AP2's only authorized key is the one the app logs in with (no openwrtgui@ key),
uhttpd is set to 443 but nothing listens there (no HTTPS), there are no opkg keys (apk) and no block-mount."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.system import commands as s
from openwrtgui.system.access import parse_dropbear, parse_listeners, parse_uhttpd
from openwrtgui.system.leds import parse_leds
from openwrtgui.system.mounts import parse_df, parse_mounts
from openwrtgui.system.sshkeys import parse_authorized_keys

RECORDING: dict[str, dict[str, object]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "access.json").read_text(encoding="utf-8")
)


def _out(command: str) -> str:
    entry = RECORDING[command]
    assert entry["exit"] == 0, entry
    return str(entry["stdout"])


def test_dropbear_parses() -> None:
    (main,) = parse_dropbear(_out(s.UCI_DROPBEAR))
    assert (main.section, main.enable, main.port, main.interface) == ("main", True, 22, "")
    assert main.password_auth and main.root_password_auth


def test_uhttpd_parses() -> None:
    http = parse_uhttpd(_out(s.UCI_UHTTPD))
    assert (http.luci_on_network, http.redirect_https, http.loopback_kept) == (True, False, True)


def test_listeners_have_ssh_and_http_but_no_https() -> None:
    listening = parse_listeners(_out(s.LISTENERS))
    ports = {port for _, port in listening}
    assert {22, 80} <= ports
    assert 443 not in ports  # configured, not served: no certificate on AP2


def test_leds_parse() -> None:
    leds = {led.sysfs: led for led in parse_leds(_out(s.LEDS))}
    assert len(leds) == 10  # seven board LEDs and three of the rt2800 radio
    assert leds["green:lan"].active == "switch0"
    assert "switch0" in leds["green:lan"].triggers


def test_one_key_the_app_logs_in_with() -> None:
    keys = [line for line in parse_authorized_keys(_out(s.KEYS_READ)) if line.type]
    assert [(k.type, k.comment) for k in keys] == [("ssh-rsa", "user@pc")]  # comment scrubbed by the recorder
    assert keys[0].fingerprint and keys[0].fingerprint.startswith("SHA256:")


def test_mounts_and_df_parse() -> None:
    mounts = {m.target: m for m in parse_mounts(_out(s.MOUNTS))}
    assert mounts["/overlay"].fstype == "jffs2"
    usage = {u.target: u for u in parse_df(_out(s.DF))}
    assert usage["/rom"].use_pct == 100


def test_what_ap2_does_not_have() -> None:
    assert RECORDING[s.HAS_BLOCK]["exit"] != 0
    assert RECORDING[s.OPKG_KEYS]["exit"] != 0
    assert _out(s.APK_KEYS).split() == ["openwrt-snapshots.pem", "public-key.pem"]
    assert "/etc/owg/" not in _out(s.KEPT)
