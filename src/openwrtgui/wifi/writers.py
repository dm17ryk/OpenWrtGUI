"""Known writers: programs that set some router options on purpose, so the app labels them instead of
flagging them (spec section 5). Editing this registry comes with baselines."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownWriter:
    name: str
    options: frozenset[str]  # wifi-device options


# dima_night sets these lab options on every AP turn (dima_night.py:265) and restores only the mode keys.
KNOWN_WRITERS = (KnownWriter("dima_night", frozenset({"country", "cell_density", "legacy_rates"})),)


def writer_of(option: str) -> str | None:
    return next((w.name for w in KNOWN_WRITERS if option in w.options), None)
