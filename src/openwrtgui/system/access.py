"""System › Access (v0.6c plan D2, D4, D6, D7): dropbear instances, uhttpd's listen lists and redirect, the
listeners the router really has, the rpcd password policy and the password rules. LuCI's own pages on this
image read exactly these (`system/dropbear.js`, `uhttpd.js`, `pwpolicy.js`)."""

from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.uci import parse_uci_show

_TRUE = frozenset({"1", "on", "yes", "true", "enabled"})
_FALSE = frozenset({"0", "off", "no", "false", "disabled"})
MAX_PASSWORD = 128

LISTEN_ALL_HTTP = ("0.0.0.0:80", "[::]:80")
LISTEN_ALL_HTTPS = ("0.0.0.0:443", "[::]:443")
LISTEN_LOOP_HTTP = ("127.0.0.1:80", "[::1]:80")
LISTEN_LOOP_HTTPS = ("127.0.0.1:443", "[::1]:443")
# what keeps 127.0.0.1:80 served: the app's LuCI pages come in through an SSH forward to it (D6)
_LOOPBACK_COVERED = frozenset({"0.0.0.0:80", "127.0.0.1:80", "80", ":80"})


class SshInstance(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: str
    enable: bool
    interface: str
    direct_interface: str
    port: int
    password_auth: bool
    root_password_auth: bool
    gateway_ports: bool


class HttpState(BaseModel):
    model_config = ConfigDict(frozen=True)

    redirect_https: bool
    luci_on_network: bool | None  # None: the router's own (custom) listen lists
    listen_http: tuple[str, ...]
    listen_https: tuple[str, ...]
    loopback_kept: bool


class PasswordPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    pw_length: int = 0
    digits: bool = False
    uc_lc: bool = False
    special_characters: bool = False


class RepoKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["apk", "opkg"]


def flag(value: str | None, default: bool) -> bool:
    """A uci flag as dropbear and LuCI read it; an absent or unknown value takes the default."""
    if value is None:
        return default
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _sections(shown: dict[str, str], kind: str) -> list[str]:
    return [path for path, value in shown.items() if path.count(".") == 1 and value == kind]


def parse_dropbear(show_text: str) -> list[SshInstance]:
    """Every `dropbear` section of `uci -X show dropbear`, with LuCI's defaults where an option is absent."""
    shown = parse_uci_show(show_text)
    out: list[SshInstance] = []
    for path in _sections(shown, "dropbear"):
        name = path.split(".", 1)[1]

        def get(option: str, base: str = path) -> str | None:
            return shown.get(f"{base}.{option}")

        port = get("Port") or "22"
        out.append(
            SshInstance(
                section=name,
                enable=flag(get("enable"), True),
                interface=get("Interface") or "",
                direct_interface=get("DirectInterface") or "",
                port=int(port) if port.isdigit() else 22,
                password_auth=flag(get("PasswordAuth"), True),
                root_password_auth=flag(get("RootPasswordAuth"), True),
                gateway_ports=flag(get("GatewayPorts"), False),
            )
        )
    return out


def _list(value: str | None) -> tuple[str, ...]:
    return tuple((value or "").split())


def parse_uhttpd(show_text: str) -> HttpState:
    """uhttpd's `main` section (the one LuCI's HTTP(S) Access page edits)."""
    shown = parse_uci_show(show_text)
    http = _list(shown.get("uhttpd.main.listen_http"))
    https = _list(shown.get("uhttpd.main.listen_https"))
    on_network: bool | None = None
    if set(http) == set(LISTEN_ALL_HTTP) and set(https) <= set(LISTEN_ALL_HTTPS):
        on_network = True
    elif set(http) == set(LISTEN_LOOP_HTTP) and set(https) <= set(LISTEN_LOOP_HTTPS):
        on_network = False
    return HttpState(
        redirect_https=flag(shown.get("uhttpd.main.redirect_https"), False),
        luci_on_network=on_network,
        listen_http=http,
        listen_https=https,
        loopback_kept=bool(_LOOPBACK_COVERED & set(http)),
    )


def _address(hex_address: str) -> str:
    raw = bytes.fromhex(hex_address)
    if len(raw) == 4:
        return str(ipaddress.IPv4Address(raw[::-1]))
    # /proc/net/tcp6 prints the address as four 32-bit words, each in host (little-endian) order
    words = b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4))
    return str(ipaddress.IPv6Address(words))


def parse_listeners(text: str) -> set[tuple[str, int]]:
    """The listening TCP sockets in `/proc/net/tcp` and `tcp6` (state 0A) as (address, port)."""
    out: set[tuple[str, int]] = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].endswith(":") or fields[3] != "0A":
            continue
        address, _, port = fields[1].partition(":")
        try:
            out.add((_address(address), int(port, 16)))
        except ValueError:
            continue
    return out


def parse_policy(show_text: str) -> PasswordPolicy | None:
    """LuCI's Password Policy: the `rpcd.policy` section, None while there is none."""
    shown = parse_uci_show(show_text)
    if shown.get("rpcd.policy") != "policy":
        return None

    def get(option: str) -> str | None:
        return shown.get(f"rpcd.policy.{option}")

    length = get("pw_length") or "0"
    return PasswordPolicy(
        enabled=flag(get("enabled"), False),
        pw_length=int(length) if length.isdigit() else 0,
        digits=flag(get("digits"), False),
        uc_lc=flag(get("uc_lc"), False),
        special_characters=flag(get("special_characters"), False),
    )


def check_password(password: str, policy: PasswordPolicy | None) -> None:
    """The rules before `passwd` gets it: one line (it goes on stdin twice), 1-128 characters, and the
    router's policy when it is enabled. The message never quotes the password."""
    if not password:
        raise ValueError("Type a password")
    if any(c in password for c in "\n\r\x00"):
        raise ValueError("The password must be one line")
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"The password is at most {MAX_PASSWORD} characters")
    if policy is None or not policy.enabled:
        return
    if len(password) < policy.pw_length:
        raise ValueError(f"The password must be at least {policy.pw_length} characters (the router's policy)")
    if policy.digits and not any(c.isdigit() for c in password):
        raise ValueError("The password needs a digit: the policy asks for a digit")
    if policy.uc_lc and not (any(c.isupper() for c in password) and any(c.islower() for c in password)):
        raise ValueError("The password needs upper and lower case letters (the router's policy)")
    if policy.special_characters and all(c.isalnum() for c in password):
        raise ValueError("The password needs a special character (the router's policy)")
