"""The router password and LuCI's password policy (plan Task 8, D2) in the simulator."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system.access import PasswordPolicy

SECRET = "Zq7-Secret-77"


def _audit_bytes(ctx: AppContext) -> bytes:
    folder = Path(ctx.data.audit_dir)
    return b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file())


async def test_password_applied_and_proven(ctx: AppContext) -> None:
    plan = await ctx.access.plan_password("ap2")
    assert plan.lines == ("passwd root",)
    assert any("logs in with its key" in w for w in plan.warnings)
    result = await ctx.access.apply_password("ap2", "N3w-Passw0rd", plan.digest)
    assert (result.applied, result.verified, result.error) == (True, True, None)
    assert [(c.name, c.ok, c.detail) for c in result.checks] == [
        ("password", True, "the router's password hash changed")
    ]


async def test_password_never_leaves_the_stdin(
    ctx: AppContext, authed: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    preview = await authed.post("/api/routers/ap2/system/password/preview")
    assert preview.status_code == 200 and preview.json()["lines"] == ["passwd root"]
    done = await authed.post(
        "/api/routers/ap2/system/password/apply",
        json={"password": SECRET, "digest": preview.json()["digest"]},
    )
    assert done.status_code == 200 and done.json()["applied"] is True
    refused = await authed.post(
        "/api/routers/ap2/system/password/apply",
        json={"password": SECRET + "\nsecond", "digest": preview.json()["digest"]},
    )
    assert refused.status_code == 422
    # a body the API cannot take (no digest): FastAPI's own 422 would echo the body back, password and all
    malformed = await authed.post("/api/routers/ap2/system/password/apply", json={"password": SECRET})
    assert malformed.status_code == 422
    for text in (preview.text, done.text, refused.text, malformed.text, caplog.text):
        assert SECRET not in text
    assert SECRET.encode() not in _audit_bytes(ctx)
    assert b"passwd root" in _audit_bytes(ctx)  # the command is audited, the password is not


@pytest.mark.parametrize(
    ("password", "reason"),
    [("", "Type a password"), ("two\nlines", "one line"), ("x" * 129, "at most 128")],
)
async def test_password_refusals(ctx: AppContext, password: str, reason: str) -> None:
    plan = await ctx.access.plan_password("ap2")
    with pytest.raises(ValueError, match=reason):
        await ctx.access.apply_password("ap2", password, plan.digest)


async def test_the_policy_is_kept(ctx: AppContext) -> None:
    policy = PasswordPolicy(enabled=True, pw_length=8, digits=True)
    plan = await ctx.access.plan_policy("ap2", policy)
    await ctx.access.apply_policy("ap2", policy, plan.digest)
    pw = await ctx.access.plan_password("ap2")
    with pytest.raises(ValueError, match="digit"):
        await ctx.access.apply_password("ap2", "abcdefgh", pw.digest)
    with pytest.raises(ValueError, match="at least 8"):
        await ctx.access.apply_password("ap2", "abc1", pw.digest)


async def test_policy_created_and_edited(ctx: AppContext) -> None:
    policy = PasswordPolicy(enabled=True, pw_length=8, digits=True)
    plan = await ctx.access.plan_policy("ap2", policy)
    assert plan.lines == (
        "set -e",
        "uci set rpcd.policy='policy'",
        "uci set rpcd.policy.enabled='1'",
        "uci set rpcd.policy.pw_length='8'",
        "uci set rpcd.policy.digits='1'",
        "uci commit rpcd",
    )
    result = await ctx.access.apply_policy("ap2", policy, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert (await ctx.access.access("ap2")).policy == policy
    off = PasswordPolicy(enabled=False, pw_length=8, digits=True)
    edit = await ctx.access.plan_policy("ap2", off)
    assert edit.lines == ("set -e", "uci set rpcd.policy.enabled='0'", "uci commit rpcd")
    with pytest.raises(ValueError, match="0-128"):
        await ctx.access.plan_policy("ap2", PasswordPolicy(enabled=True, pw_length=200))


async def test_password_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    plan = await ctx_guard_live.access.plan_password("ap2")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.access.apply_password("ap2", "N3w-Passw0rd", plan.digest)
