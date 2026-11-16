"""One rule for which option values the app shows hidden (v1.0b1 D2)."""

from __future__ import annotations

import pytest

from openwrtgui.guard.secrets import HIDDEN, is_secret_option, shown


@pytest.mark.parametrize(
    "name",
    [
        "wireless.default_radio0.key",
        "wireless.wifinet1.key3",
        "wireless.wifinet1.sae_password",
        "wireless.wifinet1.auth_secret",
        "wireless.wifinet1.r0kh",
        "wireless.wifinet1.wps_pin",
        "network.wg0.private_key",
        "network.wgpeer.preshared_key",
        "network.lte.pincode",
        "rpcd.@login[0].password",
        "luci_plugins.bb4ea47fcffb44ec9bb3d3673c9b4ed2.key_root",
        "openvpn.client.auth_token",
        "ddns.myddns.cloudflare_token",
        "apikey",
        "totpsecret",
        "priv_key_pwd",
        "snmpd.public.community",  # an SNMP community string is its password (final review)
        "acme.example.credentials",  # holds the DNS API token, CF_Token=... (final review)
    ],
)
def test_secret_options(name: str) -> None:
    assert is_secret_option(name)


@pytest.mark.parametrize(
    "name",
    [
        "wireless.default_radio0.ssid",
        "wireless.default_radio0.encryption",
        "dropbear.@dropbear[0].PasswordAuth",
        "dropbear.@dropbear[0].RootPasswordAuth",
        "network.wan.keepalive",
        "network.lan.ipaddr",
        "wireless.wifinet_key",  # a section and its type: never an option
        "mode",
    ],
)
def test_options_that_stay_shown(name: str) -> None:
    assert not is_secret_option(name)


def test_shown_hides_a_secret_value_and_keeps_none() -> None:
    assert shown("wireless.default_radio0.key", "a-made-up-key") == HIDDEN
    assert shown("wireless.default_radio0.key", None) is None
    assert shown("wireless.default_radio0.ssid", "OpenWrt") == "OpenWrt"
