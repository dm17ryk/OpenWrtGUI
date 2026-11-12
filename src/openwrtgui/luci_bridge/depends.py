"""Which LuCI pages LuCI itself shows on a router (v1.0a1 D2): its menu's `depends`, checked the way LuCI's
dispatcher.uc does, against facts the app reads from the router (D3)."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from openwrtgui.probe.luci_menu import LuciPage

_CONFIG = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Facts:
    # present paths -> "file", "executable", "directory", "empty directory" or "other"
    files: Mapping[str, str]
    # config -> parse_uci_show of `uci -q show <config>`; a config missing here is absent
    uci: Mapping[str, Mapping[str, str]]
    # the router's LuCI access groups that grant read or write
    acl: frozenset[str]
    # False: the facts could not be read, so nothing is hidden (D3)
    checked: bool = True


UNCHECKED = Facts({}, {}, frozenset(), checked=False)


def _alternatives(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _fs_alternatives(pages: Iterable[LuciPage]) -> Iterator[dict[str, Any]]:
    return (alt for page in pages for d in page.requires for alt in _alternatives(d.get("fs")))


def fs_paths(pages: Iterable[LuciPage]) -> list[str]:
    return sorted({p for alt in _fs_alternatives(pages) for p in alt})


def dir_paths(pages: Iterable[LuciPage]) -> list[str]:
    return sorted({p for alt in _fs_alternatives(pages) for p, kind in alt.items() if kind == "directory"})


def uci_configs(pages: Iterable[LuciPage]) -> list[str]:
    names = {c for page in pages for d in page.requires for alt in _alternatives(d.get("uci")) for c in alt}
    return sorted(n for n in names if _CONFIG.fullmatch(n))


def files_command(paths: Iterable[str]) -> str:
    return "ls -ldL " + " ".join(shlex.quote(p) for p in sorted(set(paths)))


def listing_command(path: str) -> str:
    return f"ls -A {shlex.quote(path)}"


def uci_command(config: str) -> str:
    if not _CONFIG.fullmatch(config):
        raise ValueError(f"{config!r} is not a uci config name")
    return f"uci -q show {config}"


def parse_ls(text: str) -> dict[str, str]:
    """Busybox `ls -ldL` lines: mode, links, owner, group, size, month, day, time or year, then the name.
    A device's size is two columns ("1,   3")."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        fields = 10 if line[:1] in ("b", "c") else 9
        parts = line.split(None, fields - 1)
        if len(parts) < fields or len(parts[0]) < 10:
            continue
        mode, name = parts[0], parts[-1]
        if mode[0] == "d":
            out[name] = "directory"
        elif mode[0] == "-":
            out[name] = "executable" if mode[3] in "xs" else "file"
        else:
            out[name] = "other"
    return out


def missing_paths(stderr: str, paths: Iterable[str]) -> set[str]:
    """Paths busybox `ls` says do not exist ("ls: /sbin/block: No such file or directory"). The listing counts
    only when every path is listed or named here (D3); any other `ls` message leaves the facts unread."""
    lines = set(stderr.splitlines())
    return {p for p in paths if f"ls: {p}: No such file or directory" in lines}


def _fs_ok(path: str, kind: str, files: Mapping[str, str]) -> bool:
    have = files.get(path)
    if kind == "absent":
        return have is None
    if kind == "executable":
        return have == "executable"
    if kind == "file":
        return have in ("file", "executable")
    if kind == "directory":
        return have == "directory"
    return False


def _fs_reason(alt: Mapping[str, str], files: Mapping[str, str]) -> str:
    path, kind = next((p, k) for p, k in alt.items() if not _fs_ok(p, k, files))
    return f"is for routers without {path}" if kind == "absent" else f"needs {path}"


def _sections(config: str, values: Mapping[str, str]) -> dict[str, tuple[str, dict[str, str]]]:
    """{section id: (type, options)} from `uci -q show` lines such as `network.@switch[0]=switch`."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for key, value in values.items():
        parts = key.split(".", 2)
        if parts[0] != config or len(parts) < 2:
            continue
        kind, options = out.get(parts[1], ("", {}))
        if len(parts) == 2:
            out[parts[1]] = (value, options)
        else:
            options[parts[2]] = value
            out[parts[1]] = (kind, options)
    return out


def _section_ok(kind: str, options: Mapping[str, str], spec: Any) -> bool:
    if spec is True:
        return bool(options)
    if isinstance(spec, str):
        return kind == spec
    if isinstance(spec, dict):
        for name, want in spec.items():
            have = options.get(name)
            if have is None:
                return False
            if want is not True and str(want) != have and str(want) not in have.split():
                return False
        return True
    return False


def _uci_alt_ok(alt: Mapping[str, Any], uci: Mapping[str, Mapping[str, str]]) -> bool:
    for config, spec in alt.items():
        sections = _sections(config, uci.get(config, {}))
        if spec is True:
            if not sections:
                return False
            continue
        if not isinstance(spec, dict):
            return False
        for name, section_spec in spec.items():
            if name.startswith("@"):
                if not any(k == name[1:] and _section_ok(k, o, section_spec) for k, o in sections.values()):
                    return False
            elif name not in sections or not _section_ok(*sections[name], section_spec):
                return False
    return True


def _uci_reason(alt: Mapping[str, Any]) -> str:
    config, spec = next(iter(alt.items()))
    if spec is True or not isinstance(spec, dict):
        return f"needs the {config} configuration"
    name, section_spec = next(iter(spec.items()))
    if not name.startswith("@"):
        return f"needs {config}.{name}"
    if isinstance(section_spec, dict):
        wanted = ", ".join(f"{k}={'set' if v is True else v}" for k, v in section_spec.items())
        return f"needs a {name[1:]} section in {config} with {wanted}"
    return f"needs a {name[1:]} section in {config}"


def _reason(depends: Mapping[str, Any], facts: Facts) -> str | None:
    for group in depends.get("acl") or ():
        if group not in facts.acl:
            return f"needs LuCI's {group} access group"
    fs = _alternatives(depends.get("fs"))
    if fs and not any(all(_fs_ok(p, k, facts.files) for p, k in alt.items()) for alt in fs):
        return _fs_reason(fs[0], facts.files)
    uci = _alternatives(depends.get("uci"))
    if uci and not any(_uci_alt_ok(alt, facts.uci) for alt in uci):
        return _uci_reason(uci[0])
    return None


def why_hidden(page: LuciPage, facts: Facts) -> str | None:
    """None when LuCI shows the page on this router; else why not (an ancestor's reason first)."""
    if not facts.checked:
        return None
    for depends in page.requires:
        reason = _reason(depends, facts)
        if reason is not None:
            return reason
    return None


def usable_groups(acl: Mapping[str, Mapping[str, Any]]) -> frozenset[str]:
    """Access groups LuCI counts: defined with a read or a write part (check_acl_depends)."""
    return frozenset(name for name, d in acl.items() if d.get("read") or d.get("write"))
