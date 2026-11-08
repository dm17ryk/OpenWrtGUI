"""A /etc/config file read into the form `uci show <config>` prints, as `uci.parse_uci_show` holds it.

Named sections are `<config>.<name>`; anonymous ones `<config>.@<type>[n]`, n counting every section of that
type from 0 (named ones too, as uci does). A list's items are joined with spaces, like `parse_uci_show`.
"""

from __future__ import annotations

import shlex


def parse_uci_file(config: str, text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    counts: dict[str, int] = {}
    section: str | None = None
    lists: dict[str, list[str]] = {}
    for line in text.splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        if not words:
            continue
        kind = words[0]
        if kind == "config" and len(words) in (2, 3):
            stype = words[1]
            index = counts.get(stype, 0)
            counts[stype] = index + 1
            section = f"{config}.{words[2]}" if len(words) == 3 else f"{config}.@{stype}[{index}]"
            out[section] = stype
        elif kind == "option" and len(words) == 3 and section is not None:
            out[f"{section}.{words[1]}"] = words[2]
        elif kind == "list" and len(words) == 3 and section is not None:
            key = f"{section}.{words[1]}"
            lists.setdefault(key, []).append(words[2])
            out[key] = " ".join(lists[key])
    return out
