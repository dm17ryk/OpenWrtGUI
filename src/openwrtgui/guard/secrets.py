"""Which uci options hold a secret, for every place the app shows option values: Discovery, Plugins and a
bridged LuCI change (v1.0b1 D2). The audit log masks commands with the exact names only."""

from __future__ import annotations

import re

HIDDEN = "<hidden>"
SECRET_OPTIONS = (
    "key",
    "key1",
    "key2",
    "key3",
    "key4",  # WEP
    "password",
    "pincode",
    "psk",
    "sae_password",
    "multi_ap_backhaul_key",  # a Wi-Fi passphrase
    "auth_secret",
    "acct_secret",
    "dae_secret",
    "auth_server_shared_secret",
    "acct_server_shared_secret",
    "priv_key_pwd",
    "priv_key2_pwd",
    "private_key_passwd",
    "private_key2_passwd",
    "wps_pin",
    "ap_pin",
    "r0kh",
    "r1kh",  # FT key holders carry their keys
    "private_key",
    "preshared_key",  # WireGuard
)
# A substring on purpose: third-party plugin options are run together (`apikey`, `totpsecret`). `cred`: acme's
# `credentials` hold the DNS API token; `community`: an SNMP community string is its password (final review).
_SECRET_PART = re.compile(r"key|secret|pass|psk|token|pin|pwd|cred|community", re.IGNORECASE)
# Names whose value is exactly what a person should see: whether password login is on (dropbear), and flags
# the substring rule caught by a word inside them (v1.0b1 final review, v1.0c D9). An unreviewed name stays
# hidden.
_SHOWN = frozenset(
    {"PasswordAuth", "RootPasswordAuth", "igmp_snooping", "ping", "mapping", "passive", "key_type"}
)


def is_secret_option(name: str) -> bool:
    """`name` is a bare option (`key`) or a `uci show` path (`wireless.default_radio0.key`). A path of two
    parts is a section and its type, never an option."""
    parts = name.split(".")
    if len(parts) == 2:
        return False
    option = parts[-1]
    if option in _SHOWN:
        return False
    return option in SECRET_OPTIONS or _SECRET_PART.search(option) is not None


def shown(name: str, value: str | None) -> str | None:
    """The value as the app shows it: hidden for a secret option; None stays None."""
    return HIDDEN if value is not None and is_secret_option(name) else value
