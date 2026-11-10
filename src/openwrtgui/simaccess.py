"""The simulated Access side of a router (v0.6c plan Task 5): dropbear's listening port (it follows the
committed config, as rpcd's apply reloads it), authorized_keys, uhttpd's listeners (they follow its config
at `/etc/init.d/uhttpd restart`), the LEDs (`/etc/init.d/led restart` applies the led sections), the root
password digest, mounts, the files kept in a backup, a restore and a reset to defaults.

The dropbear, uhttpd, rpcd and system configs live in the network simulator; this reads them committed. The
values are AP2's (tests/fixtures/ap2/access.json, 2026-11-10): no HTTPS on AP2, no block-mount, apk keys."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import tarfile
from collections.abc import Callable
from typing import TYPE_CHECKING

from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.system import commands as s
from openwrtgui.system.access import parse_dropbear
from openwrtgui.system.leds import parse_led_sections
from openwrtgui.transport.base import CommandResult
from openwrtgui.uci import shell_quote

if TYPE_CHECKING:
    from openwrtgui.simimage import SimImage
    from openwrtgui.simnet import SimNetwork
    from openwrtgui.simsystem import SimSystem
    from openwrtgui.transport.fake import SimState

# a key that is not the app's (a bench PC's), so the SSH keys tab has an "Other" row
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJvWfggOSyIPKEhT8VoBxUhNS6R/ehRIvdYmnQWrmKsS bench@lab"
_TRIGGERS = (
    "none",
    "timer",
    "heartbeat",
    "default-on",
    "netdev",
    "switch0",
    "phy0rx",
    "phy0tx",
    "phy0assoc",
    "phy0radio",
    "phy0tpt",
)
# AP2's LEDs: active trigger, brightness, max brightness
_LEDS = {
    "green:3g": ("none", 0, 1),
    "green:4g": ("none", 1, 1),
    "green:internet": ("none", 0, 1),
    "green:lan": ("switch0", 1, 1),
    "green:sigstrength": ("none", 1, 1),
    "green:wifi": ("none", 0, 1),
    "red:sigstrength": ("none", 0, 1),
    "rt2800soc-phy0::assoc": ("none", 0, 255),
    "rt2800soc-phy0::quality": ("none", 0, 255),
    "rt2800soc-phy0::radio": ("none", 0, 255),
}
NET_DEVICES = "br-lan\neth0\neth0.1\neth0.2\nlo\nteql0\nwwan0\n"
MOUNTS = (
    "/dev/root /rom squashfs ro,relatime,errors=continue 0 0\n"
    "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n"
    "sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0\n"
    "tmpfs /tmp tmpfs rw,nosuid,nodev,noatime 0 0\n"
    "/dev/mtdblock6 /overlay jffs2 rw,noatime 0 0\n"
    "overlayfs:/overlay / overlay rw,noatime,lowerdir=/,upperdir=/overlay/upper,workdir=/overlay/work 0 0\n"
    "tmpfs /dev tmpfs rw,nosuid,noexec,noatime,size=512k,mode=755 0 0\n"
)
DF = (
    "Filesystem           1K-blocks      Used Available Use% Mounted on\n"
    "/dev/root                 8192      8192         0 100% /rom\n"
    "tmpfs                    27552      1856     25696   7% /tmp\n"
    "/dev/mtdblock6            5056       396      4660   8% /overlay\n"
    "overlayfs:/overlay        5056       396      4660   8% /\n"
    "tmpfs                      512         0       512   0% /dev\n"
)
KEPT = (
    "## This file contains files and directories that should\n## be preserved during an upgrade.\n\n"
    "# /etc/example.conf\n# /etc/openvpn/\n"
)
BACKUP_LIST = "".join(
    f"{p}\n"
    for p in (
        "/etc/config/dhcp",
        "/etc/config/dropbear",
        "/etc/config/firewall",
        "/etc/config/network",
        "/etc/config/rpcd",
        "/etc/config/system",
        "/etc/config/uhttpd",
        "/etc/config/wireless",
        "/etc/dropbear/authorized_keys",
        "/etc/dropbear/dropbear_ed25519_host_key",
        "/etc/passwd",
        "/etc/rc.local",
        "/etc/shadow",
    )
)
APK_KEYS = "openwrt-snapshots.pem\npublic-key.pem\n"
_WRITE_KEYS = re.compile(
    r"mkdir -p /etc/dropbear && cat > /etc/dropbear/authorized_keys <<'OWG' && chmod 600 "
    r"/etc/dropbear/authorized_keys\n(.*)\nOWG",
    re.DOTALL,
)
_WRITE_KEPT = re.compile(r"cat > /etc/sysupgrade\.conf <<'OWG'\n(.*)\nOWG", re.DOTALL)
_DIGESTS = re.compile(r"sha256sum((?: '[^']+')+)")
_ANONYMOUS = re.compile(r"cfg[0-9a-f]{6}")
_INDEXED = re.compile(r"@([A-Za-z0-9_]+)\[(\d+)\]")


def _ok(command: str, out: str = "") -> CommandResult:
    return CommandResult(command, out, "", 0)


def _fail(command: str, err: str, status: int = 1) -> CommandResult:
    return CommandResult(command, "", err, status)


def render_uci_file(uci: dict[str, str], config: str) -> str:
    """A committed config as its /etc/config file (a list is one option here: it reads back the same)."""
    out: list[str] = []
    for section in [k for k in uci if k.startswith(config + ".") and k.count(".") == 1]:
        name = section.split(".", 1)[1]
        head = f"config {uci[section]}"
        out.append(head if _ANONYMOUS.fullmatch(name) else f"{head} {shell_quote(name)}")
        out += [
            f"\toption {k.rsplit('.', 1)[1]} {shell_quote(v)}"
            for k, v in uci.items()
            if k.startswith(section + ".") and k.count(".") == 2
        ]
        out.append("")
    return "\n".join(out)


def _named(config: str, values: dict[str, str]) -> dict[str, str]:
    """parse_uci_file names an unnamed section `<config>.@<type>[n]`; libuci names it cfgXXXXXX."""
    names: dict[str, str] = {}
    for key in values:
        section = ".".join(key.split(".")[:2])
        if _INDEXED.fullmatch(section.split(".", 1)[1]) and section not in names:
            digest = hashlib.sha1(f"{config}:{section}".encode()).hexdigest()[:6]
            names[section] = f"{config}.cfg{digest}"
    out: dict[str, str] = {}
    for key, value in values.items():
        section = ".".join(key.split(".")[:2])
        out[names.get(section, section) + key[len(section) :]] = value
    return out


def _hex_v4(address: str) -> str:
    return ipaddress.IPv4Address(address).packed[::-1].hex().upper()


def _hex_v6(address: str) -> str:
    raw = ipaddress.IPv6Address(address).packed
    return b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4)).hex().upper()


def _listen(entry: str) -> tuple[str, int] | None:
    """uhttpd's `listen_http` item: `ip:port`, `[v6]:port` or a bare port (every address)."""
    if entry.isdigit():
        return "0.0.0.0", int(entry)
    if m := re.fullmatch(r"\[([0-9a-fA-F:.]+)\]:(\d+)", entry):
        return m.group(1), int(m.group(2))
    if m := re.fullmatch(r"([\d.]+):(\d+)", entry):
        return m.group(1), int(m.group(2))
    return None


class SimAccess:
    def __init__(
        self,
        *,
        net: SimNetwork,
        state: SimState,
        system: SimSystem | None,
        image: SimImage | None = None,
        https: bool = True,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._net = net
        self._state = state
        self._system = system
        self._https = https
        self._clock = clock
        self.blocked_ports: set[int] = set()  # as a firewall that does not let a port in (tests)
        self.gone = False  # erased by firstboot: the router answers nowhere the app looks
        self._image = image  # it owns /etc/sysupgrade.conf and `sysupgrade -l` when the router has one
        self._own_kept = KEPT
        self._leds = {name: [active, bright, top] for name, (active, bright, top) in _LEDS.items()}
        self._web = self._listen_lists()  # what uhttpd listens on: its config at the last (re)start
        self._upload: bytes | None = None
        self._restored: dict[str, bytes] = {}
        if OTHER_KEY not in state.authorized_keys:
            state.authorized_keys.append(OTHER_KEY)
        if system is not None:
            system.extra_files = self.backup_files

    # ---------------------------------------------------------------- state
    @property
    def _kept(self) -> str:
        return self._image.sysupgrade_conf if self._image is not None else self._own_kept

    @_kept.setter
    def _kept(self, text: str) -> None:
        if self._image is not None:
            self._image.sysupgrade_conf = text
        else:
            self._own_kept = text

    def _uci(self) -> dict[str, str]:
        return self._net.uci()

    def _show(self, config: str) -> str:
        return "".join(
            f"{k}={shell_quote(v)}\n" for k, v in self._uci().items() if k.startswith(config + ".")
        )

    def ssh_ports(self) -> set[int]:
        return {i.port for i in parse_dropbear(self._show("dropbear")) if i.enable}

    def listens_ssh(self, port: int) -> bool:
        return not self.gone and port not in self.blocked_ports and port in self.ssh_ports()

    def _listen_lists(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        uci = self._uci()
        return (
            tuple(uci.get("uhttpd.main.listen_http", "").split()),
            tuple(uci.get("uhttpd.main.listen_https", "").split()),
        )

    def _listeners(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for port in sorted(self.ssh_ports()):
            out += [("0.0.0.0", port), ("::", port)]
        http, https = self._web
        for entry in (*http, *(https if self._https else ())):
            found = _listen(entry)
            if found is not None:
                out.append(found)
        return out

    def _proc_net_tcp(self) -> str:
        v4 = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  inode\n"
        v6 = "  sl  local_address                         remote_address                        st tx_queue\n"
        rows4 = rows6 = 0
        for address, port in self._listeners():
            if ":" in address:
                v6 += f"   {rows6}: {_hex_v6(address)}:{port:04X} {'0' * 32}:0000 0A 00000000:00000000 0 0\n"
                rows6 += 1
            else:
                v4 += f"   {rows4}: {_hex_v4(address)}:{port:04X} 00000000:0000 0A 00000000:00000000 0 0\n"
                rows4 += 1
        return v4 + v6

    def _password_digest(self) -> str:
        password = self._state.root_password
        field = "" if password is None else "sim$" + hashlib.sha256(password.encode()).hexdigest()
        return hashlib.sha256(f"{field}\n".encode()).hexdigest()

    def _led_restart(self) -> None:
        for row in parse_led_sections(self._show("system")):
            led = self._leds.get(row.sysfs)
            if led is None:
                continue
            trigger = row.trigger if row.trigger in _TRIGGERS else "none"
            led[0] = trigger
            if trigger == "none":
                led[1] = led[2] if row.default else 0
            elif trigger == "default-on":
                led[1] = led[2]

    # ---------------------------------------------------------------- files
    def _keys_text(self) -> str:
        return "".join(f"{line}\n" for line in self._state.authorized_keys)

    def _file_bytes(self, path: str) -> bytes | None:
        if path in self._restored:
            return self._restored[path]
        if path == s.AUTHORIZED_KEYS:
            return self._keys_text().encode()
        if path == "/etc/sysupgrade.conf":
            return self._kept.encode()
        if path.startswith("/etc/config/"):
            config = path.removeprefix("/etc/config/")
            if any(k.startswith(config + ".") for k in self._uci()):
                return render_uci_file(self._uci(), config).encode()
            return None
        if self._system is not None:
            text = self._system.file(path)
            return text.encode() if text is not None else None
        return None

    def backup_files(self) -> dict[str, str]:
        return {"etc/dropbear/authorized_keys": self._keys_text(), "etc/sysupgrade.conf": self._kept}

    def _members(self) -> list[tuple[str, bytes]]:
        assert self._upload is not None
        out: list[tuple[str, bytes]] = []
        with tarfile.open(fileobj=io.BytesIO(self._upload), mode="r:gz") as tar:
            for member in tar:
                handle = tar.extractfile(member) if member.isfile() else None
                out.append((member.name, handle.read() if handle else b""))
        return out

    def _restore(self, c: str) -> CommandResult:
        from openwrtgui.simnet import CONFIGS

        if self._upload is None:
            return _fail(c, f"Backup archive '{s.RESTORE_FILE}' not found\n")
        for name, data in self._members():
            path = "/" + name.lstrip("./")
            text = data.decode(errors="replace")
            config = path.removeprefix("/etc/config/")
            if path.startswith("/etc/config/") and config in CONFIGS:
                self._net.replace_config(config, _named(config, parse_uci_file(config, text)))
            elif path in ("/etc/rc.local", "/etc/crontabs/root") and self._system is not None:
                self._system.set_file(path, text)
            elif path == s.AUTHORIZED_KEYS:
                self._state.authorized_keys[:] = text.splitlines()
            elif path == "/etc/sysupgrade.conf":
                self._kept = text
            self._restored[path] = data
        return _ok(c, "")

    def _digests(self, c: str, quoted: str) -> CommandResult:
        out, err = "", ""
        for path in re.findall(r"'([^']+)'", quoted):
            data = self._file_bytes(path)
            if data is None:
                err += f"sha256sum: {path}: No such file or directory\n"
            else:
                out += f"{hashlib.sha256(data).hexdigest()}  {path}\n"
        return CommandResult(c, out, err, 1 if err else 0)

    # ---------------------------------------------------------------- commands
    def upload(self, command: str, data: bytes) -> CommandResult | None:
        if command != s.UPLOAD_RESTORE:
            return None
        self._upload = data
        return _ok(command)

    def answer(self, command: str) -> CommandResult | None:  # noqa: PLR0911 - one branch per command
        c = command
        exact: dict[str, str] = {
            s.APK_KEYS: APK_KEYS,
            s.NET_DEVICES: NET_DEVICES,
            s.MOUNTS: MOUNTS,
            s.DF: DF,
            s.BACKUP_LIST: BACKUP_LIST,
        }
        if c in exact:
            return _ok(c, exact[c])
        if c == s.KEYS_READ:
            return _ok(c, self._keys_text())
        if m := _WRITE_KEYS.fullmatch(c):
            self._state.authorized_keys[:] = m.group(1).split("\n") if m.group(1) else []
            self._restored.pop(s.AUTHORIZED_KEYS, None)
            return _ok(c)
        if c == s.KEPT:
            return _ok(c, self._kept)
        if m := _WRITE_KEPT.fullmatch(c):
            self._kept = m.group(1) + "\n"
            self._restored.pop("/etc/sysupgrade.conf", None)
            return _ok(c)
        if c == s.OPKG_KEYS:
            return _fail(c, "ls: /etc/opkg/keys: No such file or directory\n")
        if c == s.HAS_BLOCK:
            return _fail(c, "")
        if c == s.LEDS:
            leds = {
                name: {"triggers": list(_TRIGGERS), "active_trigger": a, "brightness": b, "max_brightness": m}
                for name, (a, b, m) in sorted(self._leds.items())
            }
            return _ok(c, json.dumps(leds, indent="\t") + "\n")
        if c == "/etc/init.d/led restart":
            self._led_restart()
            return _ok(c)
        if c == "/etc/init.d/uhttpd restart":
            self._web = self._listen_lists()
            return _ok(c)
        if c == s.LISTENERS:
            return _ok(c, self._proc_net_tcp())
        if c == s.PASSWORD_DIGEST:
            return _ok(c, f"{self._password_digest()}  -\n")
        if c == s.LIST_RESTORE:
            if self._upload is None:
                return _fail(c, f"tar: can't open '{s.RESTORE_FILE}': No such file or directory\n")
            return _ok(c, "".join(f"{name}\n" for name, _ in self._members()))
        if c == s.RESTORE:
            return self._restore(c)
        if c == s.REMOVE_RESTORE:
            self._upload = None
            return _ok(c)
        if m := _DIGESTS.fullmatch(c):
            return self._digests(c, m.group(1))
        if c == "firstboot -r -y":
            self.gone = True
            return _ok(c)
        return None
