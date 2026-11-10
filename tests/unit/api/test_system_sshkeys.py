"""System › Access › SSH keys (plan Task 10, D5) in the simulator: authorized_keys written whole, the
app's key kept, harness keys named."""

from __future__ import annotations

import asyncssh
import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.simaccess import OTHER_KEY
from openwrtgui.system import commands as s
from openwrtgui.system.sshkeys import KeysChange

HEAD = (
    "mkdir -p /etc/dropbear && cat > /etc/dropbear/authorized_keys <<'OWG' && chmod 600 "
    "/etc/dropbear/authorized_keys"
)


def _new_key(comment: str = "ci@lab") -> tuple[str, str]:
    key = asyncssh.generate_private_key("ssh-ed25519", comment=comment)
    return key.export_public_key("openssh").decode().strip(), key.get_fingerprint("sha256")


async def _fingerprint_of(ctx: AppContext, comment: str) -> str:
    rows = (await ctx.access.access("ap2")).keys
    found = next(k.fingerprint for k in rows if k.comment == comment)
    assert found is not None
    return found


async def test_key_added_and_removed(ctx: AppContext) -> None:
    line, fingerprint = _new_key()
    plan = await ctx.access.plan_keys("ap2", KeysChange(add=(line,)))
    assert plan.lines[0] == HEAD and line in plan.lines
    result = await ctx.access.apply_keys("ap2", KeysChange(add=(line,)), plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert [c.name for c in result.checks] == ["saved", "added", "the app still logs in"]
    row = next(k for k in (await ctx.access.access("ap2")).keys if k.fingerprint == fingerprint)
    assert (row.label, row.comment) == ("other", "ci@lab")
    drop = KeysChange(remove=(fingerprint,))
    gone = await ctx.access.apply_keys("ap2", drop, (await ctx.access.plan_keys("ap2", drop)).digest)
    assert (gone.applied, gone.verified) == (True, True)
    assert fingerprint not in {k.fingerprint for k in (await ctx.access.access("ap2")).keys}


async def test_the_apps_key_cannot_be_removed(ctx: AppContext) -> None:
    await ctx.access.access("ap2")  # the simulated router has the app's key once the app logged in
    with pytest.raises(ValueError, match="The app logs in to AP2 . office with this key"):
        await ctx.access.plan_keys("ap2", KeysChange(remove=(ctx.app_key.fingerprint,)))


async def test_harness_key_removal_warns(ctx: AppContext) -> None:
    bench = await _fingerprint_of(ctx, "bench@lab")
    ctx.access.set_key_owner(bench, "dima_night")
    row = next(k for k in (await ctx.access.access("ap2")).keys if k.fingerprint == bench)
    assert (row.label, row.owner) == ("harness", "dima_night")
    plan = await ctx.access.plan_keys("ap2", KeysChange(remove=(bench,)))
    assert "dima_night uses this key: it can no longer log in to AP2 · office" in plan.warnings
    ctx.access.set_key_owner(bench, None)
    assert next(k for k in (await ctx.access.access("ap2")).keys if k.fingerprint == bench).label == "other"
    with pytest.raises(ValueError):
        ctx.access.set_key_owner(bench, "a;b")
    with pytest.raises(ValueError):
        ctx.access.set_key_owner("not-a-fingerprint", "dima_night")


async def test_duplicate_key_refused(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="already"):
        await ctx.access.plan_keys("ap2", KeysChange(add=(OTHER_KEY,)))
    line, _ = _new_key()
    with pytest.raises(ValueError, match="already"):
        await ctx.access.plan_keys("ap2", KeysChange(add=(line, line)))
    with pytest.raises(ValueError, match="No key"):
        await ctx.access.plan_keys("ap2", KeysChange(remove=("SHA256:" + "A" * 43,)))


async def test_unknown_lines_survive_a_write(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    text = (await t.run(s.KEYS_READ)).stdout
    assert (await t.run(s.write_file("/etc/dropbear/authorized_keys", "# bench keys\n" + text))).ok
    line, _ = _new_key()
    change = KeysChange(add=(line,))
    plan = await ctx.access.plan_keys("ap2", change)
    assert plan.lines[1] == "# bench keys"
    await ctx.access.apply_keys("ap2", change, plan.digest)
    assert (await t.run(s.KEYS_READ)).stdout.startswith("# bench keys\n")


async def test_key_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    line, fingerprint = _new_key()
    preview = await authed.post(
        "/api/routers/ap2/system/ssh-keys/preview", json={"add": [line], "remove": []}
    )
    assert preview.status_code == 200
    done = await authed.post(
        "/api/routers/ap2/system/ssh-keys/apply",
        json={"add": [line], "remove": [], "digest": preview.json()["digest"]},
    )
    assert done.json()["verified"] is True
    owner = await authed.put(
        "/api/routers/ap2/system/ssh-keys/owner", json={"fingerprint": fingerprint, "owner": "txctl"}
    )
    assert owner.status_code == 200
    assert next(k for k in owner.json()["keys"] if k["fingerprint"] == fingerprint)["owner"] == "txctl"


async def test_keys_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    line, _ = _new_key()
    change = KeysChange(add=(line,))
    plan = await ctx_guard_live.access.plan_keys("ap2", change)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.access.apply_keys("ap2", change, plan.digest)
