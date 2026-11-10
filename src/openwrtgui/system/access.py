"""System › Access (v0.6c plan D2, D4, D6, D7): dropbear instances, uhttpd's listen lists and redirect, the
listeners the router really has, the rpcd password policy and the password rules. LuCI's own pages on this
image read exactly these (`system/dropbear.js`, `uhttpd.js`, `pwpolicy.js`)."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.uci import UciOp, parse_uci_show

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


def _sections(shown: Mapping[str, str], kind: str) -> list[str]:
    return [path for path, value in shown.items() if path.count(".") == 1 and value == kind]


def parse_dropbear(show_text: str) -> list[SshInstance]:
    """Every `dropbear` section of `uci -X show dropbear`, with LuCI's defaults where an option is absent."""
    return dropbear_instances(parse_uci_show(show_text))


def dropbear_instances(shown: Mapping[str, str]) -> list[SshInstance]:
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


class SshInstanceIn(BaseModel):
    """One dropbear instance as the screen sends it: section None is a new one."""

    model_config = ConfigDict(frozen=True)

    section: str | None
    enable: bool
    interface: str
    port: int
    password_auth: bool
    root_password_auth: bool
    gateway_ports: bool


class SshChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    instances: list[SshInstanceIn]
    remove: tuple[str, ...] = ()


_SSH_FLAGS = (
    ("password_auth", "PasswordAuth"),
    ("root_password_auth", "RootPasswordAuth"),
    ("gateway_ports", "GatewayPorts"),
)


def _flag_value(current: str | None, on: bool, *, onoff: bool) -> str:
    """A flag in the style its option already has (AP2: PasswordAuth 'on', enable '1')."""
    style = current.strip().lower() in ("on", "off") if current is not None else onoff
    if style:
        return "on" if on else "off"
    return "1" if on else "0"


def _app_checks(item: SshInstanceIn, app: SshInstance, router: str, app_interface: str | None) -> None:
    where = f"{app.section} (port {app.port})"
    if not item.enable:
        raise ValueError(f"The app connects to {router} through {where}: it cannot be turned off here")
    if item.interface not in ("", app_interface):
        raise ValueError(
            f"The app reaches {router} through {app_interface}: {app.section} must listen there or on every "
            "interface"
        )


def _conflicts(instances: list[SshInstance]) -> None:
    for port in {i.port for i in instances if i.enable}:
        on = [i.interface for i in instances if i.enable and i.port == port]
        if len(on) > 1 and ("" in on or len(set(on)) < len(on)):
            raise ValueError(f"Two SSH instances would listen on port {port}")


def ssh_ops(
    current: Mapping[str, str],
    change: SshChange,
    *,
    app_instance: str | None,
    app_interface: str | None,
    interfaces: set[str],
    router_name: str,
) -> tuple[list[UciOp], list[int]]:
    """The uci ops for a dropbear change, and the ports the enabled instances listen on afterwards. The
    app's own instance is never turned off, removed or moved off the app's interface (spec 6, own path)."""
    from openwrtgui.system.commands import IFACE_NAME

    existing = {i.section: i for i in dropbear_instances(current)}
    for name in change.remove:
        if name not in existing:
            raise ValueError(f"No SSH instance {name} on {router_name}")
        if name == app_instance:
            where = f"{name} (port {existing[name].port})"
            raise ValueError(f"The app connects to {router_name} through {where}: it cannot be removed here")
    final = {name: i for name, i in existing.items() if name not in change.remove}
    ops: list[UciOp] = []
    for n, item in enumerate(change.instances, start=1):
        if not 1 <= item.port <= 65535:
            raise ValueError("An SSH port is 1-65535")
        if item.section is not None and item.section not in existing:
            raise ValueError(f"No SSH instance {item.section} on {router_name}")
        if item.section is not None and item.section == app_instance:
            _app_checks(item, existing[item.section], router_name, app_interface)
        if item.interface and (not IFACE_NAME.fullmatch(item.interface) or item.interface not in interfaces):
            raise ValueError(f"No interface {item.interface} on {router_name}")
        values = item.model_dump(exclude={"section"})
        if item.section is None:
            base = f"dropbear.$ssh{n}"
            ops += [
                UciOp("add", base, "dropbear"),
                UciOp("set", f"{base}.enable", "1" if item.enable else "0"),
            ]
            ops.append(UciOp("set", f"{base}.Port", str(item.port)))
            if item.interface:
                ops.append(UciOp("set", f"{base}.Interface", item.interface))
            ops += [
                UciOp("set", f"{base}.{opt}", _flag_value(None, getattr(item, attr), onoff=True))
                for attr, opt in _SSH_FLAGS
            ]
            final[base] = SshInstance(section=base, direct_interface="", **values)
            continue
        base, old = f"dropbear.{item.section}", existing[item.section]
        if item.enable != old.enable:
            ops.append(
                UciOp(
                    "set",
                    f"{base}.enable",
                    _flag_value(current.get(f"{base}.enable"), item.enable, onoff=False),
                )
            )
        if item.port != old.port:
            ops.append(UciOp("set", f"{base}.Port", str(item.port)))
        if item.interface != old.interface:
            ops.append(
                UciOp("set", f"{base}.Interface", item.interface)
                if item.interface
                else UciOp("delete", f"{base}.Interface")
            )
        for attr, opt in _SSH_FLAGS:
            if getattr(item, attr) != getattr(old, attr):
                value = _flag_value(current.get(f"{base}.{opt}"), getattr(item, attr), onoff=True)
                ops.append(UciOp("set", f"{base}.{opt}", value))
        final[item.section] = SshInstance(
            section=item.section, direct_interface=old.direct_interface, **values
        )
    ops += [UciOp("delete", f"dropbear.{name}") for name in change.remove]
    _conflicts(list(final.values()))
    return ops, sorted({i.port for i in final.values() if i.enable})


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


def policy_ops(current: Mapping[str, str], policy: PasswordPolicy) -> list[UciOp]:
    """LuCI's Password Policy page: the named `rpcd.policy` section, flags removed when off (rmempty)."""
    if not 0 <= policy.pw_length <= MAX_PASSWORD:
        raise ValueError(f"A minimum length is 0-{MAX_PASSWORD} characters")
    base = "rpcd.policy"
    ops: list[UciOp] = []
    if current.get(base) != "policy":
        ops.append(UciOp("set", base, "policy"))
    ops.append(UciOp("set", f"{base}.enabled", "1" if policy.enabled else "0"))

    def optional(option: str, value: str | None) -> None:
        if value is not None:
            ops.append(UciOp("set", f"{base}.{option}", value))
        elif f"{base}.{option}" in current:
            ops.append(UciOp("delete", f"{base}.{option}"))

    optional("pw_length", str(policy.pw_length) if policy.pw_length > 0 else None)
    optional("digits", "1" if policy.digits else None)
    optional("uc_lc", "1" if policy.uc_lc else None)
    optional("special_characters", "1" if policy.special_characters else None)
    return ops


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
