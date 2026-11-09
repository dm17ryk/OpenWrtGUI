"""System › Services and rc.local in the simulator: actions proven by `rc list`, the app's path (D6, D7)."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked

WARNING = (
    "This restarts AP2 · office's network: devices and this app lose AP2 · office for a few seconds; "
    "the txctl session must be told"
)


def _row(rows: list, name: str):  # type: ignore[no-untyped-def,type-arg]
    return next(r for r in rows if r.name == name)


async def test_stop_then_start_sysntpd_is_proven_each_way(ctx: AppContext) -> None:
    plan = await ctx.system.plan_service("ap2", "sysntpd", "stop")
    assert plan.lines == ("/etc/init.d/sysntpd stop",) and plan.warnings == ()
    stopped = await ctx.system.apply_service("ap2", "sysntpd", "stop", plan.digest)
    assert (stopped.applied, stopped.verified) == (True, True), stopped
    assert stopped.checks[0].name == "service sysntpd" and stopped.checks[0].detail == "not running"
    assert not _row(await ctx.system.services("ap2"), "sysntpd").running
    plan = await ctx.system.plan_service("ap2", "sysntpd", "start")
    started = await ctx.system.apply_service("ap2", "sysntpd", "start", plan.digest)
    assert started.verified and started.checks[0].detail == "running"
    assert _row(await ctx.system.services("ap2"), "sysntpd").running


async def test_disable_then_enable_urandom_seed(ctx: AppContext) -> None:
    plan = await ctx.system.plan_service("ap2", "urandom_seed", "disable")
    done = await ctx.system.apply_service("ap2", "urandom_seed", "disable", plan.digest)
    assert done.verified and done.checks[0].detail == "disabled"
    assert not _row(await ctx.system.services("ap2"), "urandom_seed").enabled
    plan = await ctx.system.plan_service("ap2", "urandom_seed", "enable")
    done = await ctx.system.apply_service("ap2", "urandom_seed", "enable", plan.digest)
    assert done.verified and done.checks[0].detail == "enabled"


async def test_a_one_shot_start_is_proven_by_its_exit(ctx: AppContext) -> None:
    """`boot` runs once: procd keeps no instance, so `rc list` has no running state to read."""
    plan = await ctx.system.plan_service("ap2", "led", "restart")
    done = await ctx.system.apply_service("ap2", "led", "restart", plan.digest)
    assert done.verified and done.checks[0].detail == "ran (runs once: procd keeps no instance of it)"


async def test_a_daemon_that_does_not_stay_up_is_not_verified(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cron's init script starts nothing without a crontab (AP2, 2026-11-09)."""
    waits: list[float] = []

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(ctx.system, "_sleep", no_sleep)
    plan = await ctx.system.plan_service("ap2", "cron", "restart")
    done = await ctx.system.apply_service("ap2", "cron", "restart", plan.digest)
    assert (done.applied, done.verified) == (True, False)
    assert done.checks[0].detail == "not running after 10 s" and sum(waits) == 10.0


@pytest.mark.parametrize(("name", "action"), [("dropbear", "stop"), ("rpcd", "disable"), ("network", "stop")])
async def test_the_apps_path_is_restart_only(ctx: AppContext, name: str, action: str) -> None:
    with pytest.raises(ValueError, match=f"^Only restart is offered for {name}: "):
        await ctx.system.plan_service("ap2", name, action)  # type: ignore[arg-type]


async def test_a_network_restart_carries_the_reload_warning(ctx: AppContext) -> None:
    plan = await ctx.system.plan_service("ap2", "network", "restart")
    assert plan.warnings == (WARNING,)
    assert (await ctx.system.plan_service("ap2", "dnsmasq", "restart")).warnings == (WARNING,)
    assert (await ctx.system.plan_service("ap2", "dnsmasq", "disable")).warnings == ()


async def test_unknown_service(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="^nosuch is not an init script on AP2 · office$"):
        await ctx.system.plan_service("ap2", "nosuch", "start")
    with pytest.raises(ValueError, match="is not a service name"):
        await ctx.system.plan_service("ap2", "../x", "start")


async def test_services_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    plan = await ctx_guard_live.system.plan_service("ap2", "sysntpd", "stop")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.apply_service("ap2", "sysntpd", "stop", plan.digest)
    assert _row(await ctx_guard_live.system.services("ap2"), "sysntpd").running


RC_LOCAL = "# boot\nlogger owg-boot\nexit 0\n"


async def test_rc_local_edit_is_applied_and_read_back(ctx: AppContext) -> None:
    before = await ctx.system.rc_local("ap2")
    assert before.endswith("exit 0\n")
    plan = await ctx.system.plan_rc_local("ap2", RC_LOCAL)
    assert plan.lines == ("cat > /etc/rc.local <<'OWG'", "# boot", "logger owg-boot", "exit 0", "OWG")
    done = await ctx.system.apply_rc_local("ap2", RC_LOCAL, plan.digest)
    assert done.verified and done.checks[0].name == "saved"
    assert await ctx.system.rc_local("ap2") == RC_LOCAL
    with pytest.raises(ValueError, match="^Nothing to apply"):
        await ctx.system.plan_rc_local("ap2", RC_LOCAL.rstrip("\n"))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("logger x\n", "The last line of rc.local is exit 0: the boot waits for it"),
        ("exit 0\nlogger x\n", "The last line of rc.local is exit 0: the boot waits for it"),
        ("OWG\nexit 0\n", "The text may not contain a line that reads OWG"),
        ("#" * (9 * 1024) + "\nexit 0\n", "The file is at most 8 KiB"),
    ],
)
async def test_rc_local_refusals(ctx: AppContext, text: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        await ctx.system.plan_rc_local("ap2", text)


async def test_services_and_rc_local_endpoints(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap2/system"
    preview = await authed.post(f"{base}/service/preview", json={"name": "sysntpd", "action": "restart"})
    assert preview.status_code == 200 and preview.json()["lines"] == ["/etc/init.d/sysntpd restart"]
    applied = await authed.post(
        f"{base}/service/apply",
        json={"name": "sysntpd", "action": "restart", "digest": preview.json()["digest"]},
    )
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
    refused = await authed.post(f"{base}/service/preview", json={"name": "dropbear", "action": "stop"})
    assert refused.status_code == 422 and refused.json()["detail"].startswith(
        "Only restart is offered for dropbear"
    )
    current = await authed.get(f"{base}/rc-local")
    assert current.status_code == 200 and current.json()["text"].endswith("exit 0\n")
    preview = await authed.post(f"{base}/rc-local/preview", json={"text": RC_LOCAL})
    applied = await authed.post(
        f"{base}/rc-local/apply", json={"text": RC_LOCAL, "digest": preview.json()["digest"]}
    )
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
