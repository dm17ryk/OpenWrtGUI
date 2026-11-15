"""v1.0a2's writes under Bench Guard at HTTP (v1.0b1 D8): previewed while clear, a harness run starts, the
apply answers 423 and sends nothing."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.simulator import SIM_GUARD_ENV
from openwrtgui.store.routers import RouterRecord

# (path under /api/routers/ap4/, the preview body; None: the mount points as read, the first one disabled)
WRITES: list[tuple[str, dict[str, object] | None]] = [
    ("system/plugins", {"enabled": False}),
    ("system/fstab", None),
    ("system/fstab/generate", {}),
    ("system/fstab/unmount", {"target": "/mnt/usb"}),
    ("system/fstab/mount", {}),
    ("firewall/iptables/reset", {}),
    ("firewall/iptables/restart", {}),
]


def add_ap4(c: AppContext) -> None:
    c.routers.upsert(
        RouterRecord(
            id="ap4",
            name="AP4 · later image",
            host="192.168.1.6",
            auth="key",
            added_at=datetime(2026, 11, 14, 9, 0),
        )
    )


async def _entries(authed: httpx.AsyncClient) -> dict[str, object]:
    first, second = (await authed.get("/api/routers/ap4/system/fstab")).json()["entries"]
    return {"entries": [{**first, "enabled": False}, second]}


@pytest.mark.parametrize(("path", "body"), WRITES, ids=[w[0] for w in WRITES])
async def test_a_previewed_write_is_refused_once_a_run_starts(
    ctx: AppContext,
    authed: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: dict[str, object] | None,
) -> None:
    add_ap4(ctx)
    base = f"/api/routers/ap4/{path}"
    change = body if body is not None else await _entries(authed)
    preview = await authed.post(f"{base}/preview", json=change)
    assert preview.status_code == 200, preview.text
    monkeypatch.setenv(SIM_GUARD_ENV, "live")
    assert ctx.guard.check_local().live
    before = len(ctx.audit.query())
    applied = await authed.post(f"{base}/apply", json={**change, "digest": preview.json()["digest"]})
    assert applied.status_code == 423, applied.text
    assert applied.json()["guard"]["live"] is True
    assert len(ctx.audit.query()) == before  # nothing was sent
