"""Mount points with block-mount (v1.0a2 D5): /etc/config/fstab as LuCI's Mount Points page edits it.

`global` holds LuCI's five flags (and delay_root, kept); `mount` and `swap` sections name their device by
UUID, else label, else device, as fstools reads them. Every value matches a rule before it reaches a uci line.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.uci import UciOp

MOUNT_PATH = re.compile(r"/[A-Za-z0-9._/-]{0,254}")
UUID = re.compile(r"[0-9A-Fa-f][0-9A-Fa-f-]{3,63}")
LABEL = re.compile(r"[A-Za-z0-9 ._-]{1,32}")  # quoted in every line it goes into
DEVICE = re.compile(r"/dev/[A-Za-z0-9._/-]{1,64}")
FSTYPE = re.compile(r"[a-z0-9]{1,16}")
OPTIONS = re.compile(r"[A-Za-z0-9,=._:/+-]{1,255}")
PROTECTED = re.compile(r"/(?:overlay|rom|tmp(?:/.+)?|dev(?:/.+)?|)")  # LuCI offers no Unmount for these
# D5: extroot (/, /overlay) and the router's own file systems are no mount targets here
REFUSED_TARGET = re.compile(r"/(?:|overlay|rom|(?:tmp|dev|proc|sys)(?:/.*)?)")
FLAGS = ("anon_swap", "anon_mount", "auto_swap", "auto_mount", "check_fs")
_CONFIG = re.compile(r"config\s+'?(\w+)'?")
_OPTION = re.compile(r"option\s+'?(\w+)'?\s+'([^']*)'")
Getter = Callable[[str], str | None]


class FstabGlobal(BaseModel):
    model_config = ConfigDict(frozen=True)

    anon_swap: bool = False
    anon_mount: bool = False
    auto_swap: bool = True
    auto_mount: bool = True
    check_fs: bool = False
    delay_root: int | None = None  # not shown (LuCI shows it neither); kept, and written by Generate


class FstabEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: str | None = None  # None: a new section
    kind: Literal["mount", "swap"]
    enabled: bool = True
    uuid: str | None = None
    label: str | None = None
    device: str | None = None
    target: str | None = None  # mounts only
    fstype: str | None = None
    options: str | None = None


class BlockDevice(BaseModel):
    model_config = ConfigDict(frozen=True)

    dev: str
    uuid: str | None = None
    label: str | None = None
    type: str | None = None
    size: int | None = None
    mount: str | None = None


class FstabState(BaseModel):
    model_config = ConfigDict(frozen=True)

    block: bool  # block-mount is installed: without it LuCI has no Mount Points page
    settings: FstabGlobal = FstabGlobal()
    global_section: str | None = None
    entries: list[FstabEntry] = []
    devices: list[BlockDevice] = []
    missing: tuple[str, ...] = ()  # "fstab config", "block devices": what could not be read


class FstabChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    settings: FstabGlobal | None = None
    entries: list[FstabEntry] | None = None  # the whole list as edited: a section left out is deleted


def _flags(get: Getter, defaults: FstabGlobal) -> dict[str, bool]:
    return {f: (getattr(defaults, f) if get(f) is None else get(f) == "1") for f in FLAGS}


def _delay(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None


def _entry(kind: str, get: Getter, section: str | None) -> FstabEntry:
    mount = kind == "mount"
    return FstabEntry(
        section=section,
        kind="mount" if mount else "swap",
        enabled=(get("enabled") or "1") == "1",
        uuid=get("uuid"),
        label=get("label"),
        device=get("device"),
        target=get("target") if mount else None,
        fstype=get("fstype") if mount else None,
        options=get("options") if mount else None,
    )


def _getter(uci: Mapping[str, str], section: str) -> Getter:
    return lambda option: uci.get(f"fstab.{section}.{option}")


def parse_fstab(uci: Mapping[str, str]) -> tuple[str | None, FstabGlobal, list[FstabEntry]]:
    sections = [
        (k.split(".", 1)[1], v) for k, v in uci.items() if k.startswith("fstab.") and k.count(".") == 1
    ]
    name = next((n for n, kind in sections if kind == "global"), None)
    settings = FstabGlobal()
    if name is not None:
        get = _getter(uci, name)
        settings = FstabGlobal(**_flags(get, settings), delay_root=_delay(get("delay_root")))
    entries = [_entry(kind, _getter(uci, n), n) for n, kind in sections if kind in ("mount", "swap")]
    return name, settings, entries


def _text(info: Mapping[str, object], key: str) -> str | None:
    value = info.get(key)
    return value if isinstance(value, str) else None


def parse_block_devices(text: str) -> list[BlockDevice]:
    """`ubus call luci getBlockDevices`: {dev: {dev, uuid, label, type, size, mount}}; anything else: none."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    devices = []
    for info in data.values():
        if isinstance(info, dict) and isinstance(info.get("dev"), str):
            size = info.get("size")
            devices.append(
                BlockDevice(
                    dev=info["dev"],
                    uuid=_text(info, "uuid"),
                    label=_text(info, "label"),
                    type=_text(info, "type"),
                    size=size if isinstance(size, int) else None,
                    mount=_text(info, "mount"),
                )
            )
    return sorted(devices, key=lambda d: d.dev)


def present(entry: FstabEntry, devices: Sequence[BlockDevice]) -> BlockDevice | None:
    """The device an entry names now, matched as LuCI does: UUID (any case), then label, then device."""
    for d in devices:
        if entry.uuid and d.uuid and entry.uuid.lower() == d.uuid.lower():
            return d
    for d in devices:
        if not entry.uuid and entry.label and d.label == entry.label:
            return d
    for d in devices:
        if not entry.uuid and not entry.label and entry.device and d.dev == entry.device:
            return d
    return None


def parse_detect(text: str) -> tuple[FstabGlobal, list[FstabEntry]]:
    """What `block detect` prints (an fstab in uci file syntax)."""
    blocks: list[tuple[str, dict[str, str]]] = []
    for line in text.splitlines():
        s = line.strip()
        if m := _CONFIG.fullmatch(s):
            blocks.append((m.group(1), {}))
        elif (m := _OPTION.fullmatch(s)) and blocks:
            blocks[-1][1][m.group(1)] = m.group(2)
    settings = FstabGlobal()
    entries: list[FstabEntry] = []
    for kind, opts in blocks:
        if kind == "global":
            settings = FstabGlobal(**_flags(opts.get, settings), delay_root=_delay(opts.get("delay_root")))
        elif kind in ("mount", "swap"):
            entries.append(_entry(kind, opts.get, None))
    return settings, entries


def _checked(rule: re.Pattern[str], value: str, what: str) -> str:
    if not rule.fullmatch(value):
        raise ValueError(f"{value!r} is not {what}")
    return value


def check_entry(e: FstabEntry, *, detected: bool = False) -> None:
    """`detected`: an entry block detect printed (Generate). A disabled one may name the router's own file
    system, as block detect writes /rom and /overlay disabled on a real router (final review)."""
    if e.uuid:
        _checked(UUID, e.uuid, "a UUID")
    elif e.label:
        _checked(LABEL, e.label, "a label (letters, digits, spaces, . _ -)")
    elif e.device:
        _checked(DEVICE, e.device, "a device under /dev")
    else:
        raise ValueError(f"A {e.kind} names its device by UUID, label or device")
    if e.kind != "mount":
        return
    if not e.target:
        raise ValueError("A mount needs a mount point")
    _checked(MOUNT_PATH, e.target, "a mount point (an absolute path of letters, digits, . _ - /)")
    # final review: `..`, `.` or `//` would walk around the refused set (/mnt/../overlay is /overlay)
    if e.target != "/" and any(part in ("", ".", "..") for part in e.target.rstrip("/").split("/")[1:]):
        raise ValueError(f"{e.target} is not a plain mount point (no '.', '..' or '//' in it)")
    if _refused(e.target) and not (detected and not e.enabled):
        raise ValueError(
            f"{e.target} is the router's own file system: set up extroot or system mounts in LuCI or the "
            "terminal"
        )
    if e.fstype:
        _checked(FSTYPE, e.fstype, "a file system type")
    if e.options:
        _checked(OPTIONS, e.options, "mount options (letters, digits and , = . _ : / + -)")


def _option(path: str, name: str, value: str | None, new: bool) -> list[UciOp]:
    if value:
        return [UciOp("set", f"{path}.{name}", value)]
    return [] if new else [UciOp("delete", f"{path}.{name}")]  # a new section has nothing to delete


def _entry_ops(path: str, e: FstabEntry, new: bool) -> list[UciOp]:
    ops = [UciOp("set", f"{path}.enabled", "1" if e.enabled else "0")]
    # one name for the device, as LuCI writes it: UUID, else label, else device
    ops += _option(path, "uuid", e.uuid, new)
    ops += _option(path, "label", None if e.uuid else e.label, new)
    ops += _option(path, "device", None if (e.uuid or e.label) else e.device, new)
    if e.kind == "mount":
        for name in ("target", "fstype", "options"):
            ops += _option(path, name, getattr(e, name), new)
    return ops


def fstab_ops(global_section: str | None, current: Sequence[FstabEntry], change: FstabChange) -> list[UciOp]:
    """Section names from the client reach a uci path unquoted: they are checked against the router's own
    (`kinds`); every value is quoted by render_uci."""
    ops: list[UciOp] = []
    if change.settings is not None:
        path = f"fstab.{global_section}" if global_section else "fstab.$g"
        if global_section is None:
            ops.append(UciOp("add", path, "global"))
        ops += [UciOp("set", f"{path}.{f}", "1" if getattr(change.settings, f) else "0") for f in FLAGS]
        if change.settings.delay_root is not None:
            ops.append(UciOp("set", f"{path}.delay_root", str(change.settings.delay_root)))
    if change.entries is not None:
        ops += _entries_ops(current, change.entries)
    return ops


def _guarded(e: FstabEntry) -> bool:
    """An enabled mount on the router's own file system (extroot): never changed or removed here (D5)."""
    return e.kind == "mount" and e.enabled and bool(e.target) and _refused(e.target or "")


def _refused(target: str) -> bool:
    return REFUSED_TARGET.fullmatch(target.rstrip("/") or "/") is not None


def _entries_ops(
    current: Sequence[FstabEntry], entries: Sequence[FstabEntry], *, detected: bool = False
) -> list[UciOp]:
    """Only new and changed entries are checked and written: an untouched one (even outside the rules, as a
    router may hold it) is left as it is (final review)."""
    now = {e.section: e for e in current if e.section}
    ops: list[UciOp] = []
    kept: set[str] = set()
    for i, e in enumerate(entries, 1):
        if e.section is not None and now.get(e.section) == e:
            kept.add(e.section)
            continue
        check_entry(e, detected=detected)
        if e.section is None:
            path = f"fstab.$m{i}"
            ops += [UciOp("add", path, e.kind), *_entry_ops(path, e, new=True)]
            continue
        if e.section not in now or now[e.section].kind != e.kind:
            raise ValueError(f"No {e.kind} section {e.section} on this router")
        kept.add(e.section)
        ops += _entry_ops(f"fstab.{e.section}", e, new=False)
    for section in sorted(set(now) - kept):
        if _guarded(now[section]):
            raise ValueError(
                f"{now[section].target} is the router's own file system (extroot): remove it in LuCI or the "
                "terminal"
            )
        ops.append(UciOp("delete", f"fstab.{section}"))
    return ops


def generate_ops(global_section: str | None, current: Sequence[FstabEntry], detected: str) -> list[UciOp]:
    """LuCI's Generate Config (D5): every section replaced with what `block detect` printed."""
    if not detected.strip():
        raise ValueError("block detect printed nothing")
    settings, entries = parse_detect(detected)
    old = [s for s in [global_section, *(e.section for e in current)] if s]
    return [
        *(UciOp("delete", f"fstab.{s}") for s in old),
        *fstab_ops(None, [], FstabChange(settings=settings)),
        *_entries_ops([], entries, detected=True),
    ]
