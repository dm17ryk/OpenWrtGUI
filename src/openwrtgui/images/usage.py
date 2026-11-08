"""The usage text of a shell script, read from its text; nothing is run.

In order: the first heredoc inside a `usage()` function; else the `echo`/`printf` lines that say "usage:";
else the first line holding "Usage:". At most 4 KB.
"""

from __future__ import annotations

import re
import shlex

MAX_USAGE = 4096
_USAGE_FN = re.compile(r"^\s*usage\s*\(\s*\)")
_HEREDOC = re.compile(r"<<(-?)\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_ECHO = re.compile(r"(?i)^\s*(echo|printf)\s.*usage:")


def _heredoc(lines: list[str]) -> str | None:
    for start, line in enumerate(lines):
        if not _USAGE_FN.match(line):
            continue
        for at in range(start, min(start + 20, len(lines))):
            found = _HEREDOC.search(lines[at])
            if not found:
                continue
            dash, delimiter = found.group(1), found.group(2)
            body: list[str] = []
            for text in lines[at + 1 :]:
                if (text.strip() if dash else text) == delimiter:
                    return "\n".join(body)
                body.append(text.lstrip("\t") if dash else text)
            return None
    return None


def _echoed(line: str) -> str:
    try:
        words = shlex.split(line)
    except ValueError:
        return line.strip()
    return " ".join(w for w in words[1:] if not w.startswith("-"))


def usage_text(script: bytes) -> str | None:
    if not script.startswith(b"#!"):
        return None
    lines = script.decode("utf-8", "replace").splitlines()
    text = _heredoc(lines)
    if text is None:
        echoed = [_echoed(line) for line in lines if _ECHO.match(line)]
        text = "\n".join(echoed) if echoed else None
    if text is None:
        text = next((line.strip() for line in lines if "Usage:" in line), None)
    if text is None or not text.strip():
        return None
    return text.strip()[:MAX_USAGE]
