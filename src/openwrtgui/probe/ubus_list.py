"""Parse `ubus -v list`: every service on the router and its method signatures."""

from __future__ import annotations

import json
import re

_OBJECT = re.compile(r"^'([^']+)' @[0-9a-f]+$")
_METHOD = re.compile(r'^\s+"([^"]+)":(\{.*\})\s*$')


def parse_ubus_list(text: str) -> dict[str, dict[str, dict[str, str]]]:
    services: dict[str, dict[str, dict[str, str]]] = {}
    current: dict[str, dict[str, str]] | None = None
    for line in text.splitlines():
        obj = _OBJECT.match(line.strip())
        if obj:
            current = services.setdefault(obj.group(1), {})
            continue
        method = _METHOD.match(line)
        if method and current is not None:
            current[method.group(1)] = json.loads(method.group(2))
    return services
