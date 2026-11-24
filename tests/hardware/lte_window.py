"""The 1.3a AP2 window's helpers on this PC: a fast sample of netifd's LTE setup processes and the gaps
between them (final review I4), and waiting for such a gap before the test's own APN restore, which reloads
lte as Recover's rung 1 does (final review I1)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

SAMPLE_STEP_S = 0.25
# on the router: uptime, then the qmi.sh count and the uqmi count, every SAMPLE_STEP_S, {n} times
SAMPLE_LOOP = (
    "i=0; while [ $i -lt {n} ]; do "
    "echo \"$(cut -d' ' -f1 /proc/uptime) $(ps w | grep -c '[q]mi\\.sh') $(ps w | grep -c '[u]qmi ')\"; "
    "sleep 0.25 2>/dev/null || usleep 250000; i=$((i+1)); done"
)


def parse_samples(text: str) -> list[tuple[float, int, int]]:
    """SAMPLE_LOOP's lines as (uptime, qmi.sh count, uqmi count); any other line is skipped."""
    samples: list[tuple[float, int, int]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            samples.append((float(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return samples


def gap_widths(samples: Sequence[tuple[float, int]]) -> list[float]:
    """Each run of idle samples (count 0) between busy ones: from its first idle sample to the next busy one,
    in seconds. A run not closed by a busy sample, or before the first, is not a gap between setups."""
    widths: list[float] = []
    seen_busy = False
    idle_since: float | None = None
    for at, count in samples:
        if count:
            if seen_busy and idle_since is not None:
                widths.append(round(at - idle_since, 3))
            seen_busy, idle_since = True, None
        elif seen_busy and idle_since is None:
            idle_since = at
    return widths


async def wait_for_gap(
    idle: Callable[[], Awaitable[bool]],
    *,
    limit_s: float,
    step_s: float,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Reads `idle` every `step_s` until it is True (a gap: returns at once) or `limit_s` has passed."""
    start = clock()
    while True:
        if await idle():
            return True
        if clock() - start >= limit_s:
            return False
        await sleep(step_s)
