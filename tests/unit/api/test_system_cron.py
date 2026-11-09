"""System › Scheduled tasks in the simulator: the crontab as text, cron enabled and restarted (v0.6b D7)."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked

TASK = "*/5 * * * * logger owg-test"
HEAD = "mkdir -p /etc/crontabs && cat > /etc/crontabs/root <<'OWG'"


async def test_no_crontab_file_is_no_tasks(ctx: AppContext) -> None:
    state = await ctx.system.crontab("ap2")
    assert (state.text, state.tasks, state.note) == ("", [], None)
    assert (state.cron_enabled, state.cron_running) == (True, False)  # AP2: enabled, idle without a crontab
    with pytest.raises(ValueError, match="^Nothing to apply"):
        await ctx.system.plan_crontab("ap2", "\n")


async def test_a_task_is_previewed_applied_and_proven(ctx: AppContext) -> None:
    plan = await ctx.system.plan_crontab("ap2", TASK)
    assert plan.lines == (HEAD, TASK, "OWG", "/etc/init.d/cron restart")
    done = await ctx.system.apply_crontab("ap2", TASK, plan.digest)
    assert (done.applied, done.verified) == (True, True), done
    assert {c.name: c.detail for c in done.checks} == {
        "saved": "the router has the new file",
        "cron": "running",
    }
    state = await ctx.system.crontab("ap2")
    assert state.text == TASK + "\n" and state.cron_running
    assert [(t.minute, t.command) for t in state.tasks] == [("*/5", "logger owg-test")]
    with pytest.raises(ValueError, match="^Nothing to apply"):
        await ctx.system.plan_crontab("ap2", TASK + "\n")


async def test_cron_is_enabled_when_it_is_disabled(ctx: AppContext) -> None:
    off = await ctx.system.plan_service("ap2", "cron", "disable")
    await ctx.system.apply_service("ap2", "cron", "disable", off.digest)
    plan = await ctx.system.plan_crontab("ap2", TASK)
    assert plan.lines[-2:] == ("/etc/init.d/cron enable", "/etc/init.d/cron restart")
    done = await ctx.system.apply_crontab("ap2", TASK, plan.digest)
    assert done.verified and (await ctx.system.crontab("ap2")).cron_enabled


async def test_removing_every_task_needs_no_running_cron(ctx: AppContext) -> None:
    plan = await ctx.system.plan_crontab("ap2", TASK)
    await ctx.system.apply_crontab("ap2", TASK, plan.digest)
    plan = await ctx.system.plan_crontab("ap2", "# none\n")
    done = await ctx.system.apply_crontab("ap2", "# none\n", plan.digest)
    assert done.verified and [c.name for c in done.checks] == ["saved"]
    assert (await ctx.system.crontab("ap2")).tasks == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# ok\n* * * * logger", "line 2: a task is five time fields and a command"),
        ("* * * * logger x", "line 1: weekday is 0-7 or sun-sat"),
        ("61 * * * * logger x", "line 1: minute is 0-59"),
        (f"{TASK}\nOWG", "line 2: a task is five time fields and a command"),  # never reaches the heredoc
        ("#" * (9 * 1024), "The file is at most 8 KiB"),
    ],
)
async def test_crontab_refusals(ctx: AppContext, text: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        await ctx.system.plan_crontab("ap2", text)


async def test_crontab_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    plan = await ctx_guard_live.system.plan_crontab("ap2", TASK)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.apply_crontab("ap2", TASK, plan.digest)
    assert (await ctx_guard_live.system.crontab("ap2")).text == ""


async def test_crontab_endpoints(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap2/system/crontab"
    current = await authed.get(base)
    assert current.status_code == 200 and current.json()["tasks"] == []
    preview = await authed.post(f"{base}/preview", json={"text": TASK})
    assert preview.status_code == 200 and preview.json()["lines"][1] == TASK
    applied = await authed.post(f"{base}/apply", json={"text": TASK, "digest": preview.json()["digest"]})
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
    bad = await authed.post(f"{base}/preview", json={"text": "61 * * * * x"})
    assert (bad.status_code, bad.json()["detail"]) == (422, "line 1: minute is 0-59")
