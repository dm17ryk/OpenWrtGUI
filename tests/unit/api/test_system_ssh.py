"""System › Access › SSH (plan Task 9, D4): dropbear instances through the rpcd rollback, the app's own
instance kept, a port change followed. In the simulator."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system.access import SshChange, SshInstanceIn

SESSION_SET = "uci -P /var/run/rpcd/uci-<session> set"


def _main(**changed: Any) -> SshInstanceIn:
    fields: dict[str, Any] = {
        "section": "main",
        "enable": True,
        "interface": "",
        "port": 22,
        "password_auth": True,
        "root_password_auth": True,
        "gateway_ports": False,
    }
    return SshInstanceIn(**(fields | changed))


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(ctx.access._runner, "_sleep", no_sleep)
    monkeypatch.setattr(ctx.access, "_sleep", no_sleep)


async def test_port_change_follows_and_confirms(ctx: AppContext) -> None:
    change = SshChange(instances=[_main(port=2222)])
    plan = await ctx.access.plan_ssh("ap2", change)
    assert plan.rollback and plan.target_port == 2222
    assert f"{SESSION_SET} dropbear.main.Port='2222'" in plan.lines
    assert any("The app follows AP2" in w and "port 2222" in w for w in plan.warnings)
    result = await ctx.access.apply_ssh("ap2", change, plan.digest)
    assert (result.applied, result.verified, result.error) == (True, True, None)
    assert ctx.routers.get("ap2").port == 2222  # type: ignore[union-attr]
    back = SshChange(instances=[_main(port=22)])
    undo = await ctx.access.apply_ssh("ap2", back, (await ctx.access.plan_ssh("ap2", back)).digest)
    assert (undo.applied, undo.verified) == (True, True)
    assert ctx.routers.get("ap2").port == 22  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (SshChange(instances=[_main(enable=False)]), "The app connects to AP2"),
        (SshChange(instances=[], remove=("main",)), "The app connects to AP2"),
        (SshChange(instances=[_main(interface="wan")]), "The app reaches AP2 . office through lan"),
    ],
)
async def test_the_apps_ssh_path_is_kept(ctx: AppContext, change: SshChange, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        await ctx.access.plan_ssh("ap2", change)


async def test_the_apps_interface_is_allowed(ctx: AppContext) -> None:
    plan = await ctx.access.plan_ssh("ap2", SshChange(instances=[_main(interface="lan")]))
    assert f"{SESSION_SET} dropbear.main.Interface='lan'" in plan.lines


async def test_a_second_instance_added_and_removed(ctx: AppContext) -> None:
    extra = SshInstanceIn(
        section=None,
        enable=True,
        interface="lan",
        port=2222,
        password_auth=False,
        root_password_auth=False,
        gateway_ports=False,
    )
    add = SshChange(instances=[extra])
    plan = await ctx.access.plan_ssh("ap2", add)
    assert any(line.endswith("add dropbear dropbear)") for line in plan.lines)
    assert plan.target_port is None  # the app stays on main
    result = await ctx.access.apply_ssh("ap2", add, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    access = await ctx.access.access("ap2")
    assert sorted(i.port for i in access.ssh) == [22, 2222] and access.app_instance == "main"
    added = next(i.section for i in access.ssh if i.port == 2222)
    drop = SshChange(instances=[], remove=(added,))
    gone = await ctx.access.apply_ssh("ap2", drop, (await ctx.access.plan_ssh("ap2", drop)).digest)
    assert (gone.applied, gone.verified) == (True, True)
    assert [i.port for i in (await ctx.access.access("ap2")).ssh] == [22]


async def test_ssh_refusals(ctx: AppContext) -> None:
    twice = SshInstanceIn(
        section=None,
        enable=True,
        interface="",
        port=22,
        password_auth=True,
        root_password_auth=True,
        gateway_ports=False,
    )
    with pytest.raises(ValueError, match="port 22"):
        await ctx.access.plan_ssh("ap2", SshChange(instances=[twice]))
    with pytest.raises(ValueError, match="1-65535"):
        await ctx.access.plan_ssh("ap2", SshChange(instances=[_main(port=70000)]))
    with pytest.raises(ValueError, match="No interface"):
        await ctx.access.plan_ssh(
            "ap2", SshChange(instances=[twice.model_copy(update={"port": 2200, "interface": "nope"})])
        )
    with pytest.raises(ValueError, match="No SSH instance"):
        await ctx.access.plan_ssh("ap2", SshChange(instances=[_main(section="other")]))


async def test_password_auth_off_warns(ctx: AppContext) -> None:
    plan = await ctx.access.plan_ssh("ap2", SshChange(instances=[_main(password_auth=False)]))
    assert f"{SESSION_SET} dropbear.main.PasswordAuth='off'" in plan.lines  # AP2 writes on/off: kept
    assert any("with a password lose SSH access" in w for w in plan.warnings)


async def test_unchanged_flags_are_not_written(ctx: AppContext) -> None:
    plan = await ctx.access.plan_ssh("ap2", SshChange(instances=[_main(gateway_ports=True)]))
    sets = [line for line in plan.lines if line.startswith(SESSION_SET)]
    assert sets == [f"{SESSION_SET} dropbear.main.GatewayPorts='on'"]
    with pytest.raises(ValueError, match="Nothing"):
        await ctx.access.plan_ssh("ap2", SshChange(instances=[_main()]))


async def test_ssh_endpoints(authed: httpx.AsyncClient) -> None:
    body = {"instances": [_main(gateway_ports=True).model_dump()], "remove": []}
    preview = await authed.post("/api/routers/ap2/system/ssh/preview", json=body)
    assert preview.status_code == 200 and preview.json()["rollback"] is True


async def test_ssh_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    change = SshChange(instances=[_main(gateway_ports=True)])
    plan = await ctx_guard_live.access.plan_ssh("ap2", change)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.access.apply_ssh("ap2", change, plan.digest)
