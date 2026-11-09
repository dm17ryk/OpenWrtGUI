"""The System screen's reads in the simulator: overview, logs, processes, services, time zones."""

from __future__ import annotations

import httpx

from openwrtgui.context import AppContext
from openwrtgui.system import commands as s
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport


async def _sim(ctx: AppContext) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.system is not None
    return t


async def _refuse(ctx: AppContext, *commands: str) -> None:
    system = (await _sim(ctx)).state.system  # type: ignore[union-attr]
    assert system is not None
    real = system.answer

    def refusing(command: str) -> CommandResult | None:
        return (
            CommandResult(command, "", "Command failed: Not found\n", 4)
            if command in commands
            else real(command)
        )

    system.answer = refusing  # type: ignore[method-assign]


async def test_overview_of_sim_ap2(ctx: AppContext) -> None:
    o = await ctx.system.overview("ap2")
    assert (o.model, o.board_name, o.hostname, o.kernel) == (
        "D-Link DWR-921 C3 (U-Boot)",
        "dlink,dwr-921-c3-uboot",
        "OpenWrt",
        "6.18.41",
    )
    assert o.load == (0.16, 0.03, 0.01) and o.memory_total == 56426496 and o.uptime_s and o.uptime_s >= 86400
    assert o.missing == ()


async def test_status_without_optional_parts(ctx: AppContext) -> None:
    await _refuse(ctx, s.BOARD, s.TIMEZONES)
    o = await ctx.system.overview("ap2")
    assert o.missing == ("board",) and o.model is None and o.uptime_s is not None  # the rest still shows
    zones = await ctx.system.timezones("ap2")
    assert zones.zones == ["UTC"]
    assert (
        zones.note
        == "This router lists no time zones (LuCI's rpcd plugin is missing): only UTC can be chosen"
    )


async def test_logs_both_kinds(ctx: AppContext) -> None:
    system = await ctx.system.logs("ap2", "system", 100)
    assert system and all(e.time and e.level for e in system)
    assert any(e.source == "dropbear" and e.pid == 24543 for e in system)
    kernel = await ctx.system.logs("ap2", "kernel", 100)
    assert (
        kernel[0].level == "notice"
        and kernel[0].seconds == 0.0
        and kernel[0].message.startswith("Linux version")
    )


async def test_processes_by_cpu(ctx: AppContext) -> None:
    p = await ctx.system.processes("ap2")
    assert p.column == "RSS" and p.cpu and "idle" in p.cpu
    assert p.rows[0].command == "top -bn1"  # 9 % CPU, the busiest
    assert [r.cpu_pct for r in p.rows] == sorted((r.cpu_pct for r in p.rows), reverse=True)


async def test_services_with_the_apps_path_protected(ctx: AppContext) -> None:
    rows = {r.name: r for r in await ctx.system.services("ap2")}
    assert rows["dropbear"].protected and "SSH" in rows["dropbear"].protected
    assert rows["network"].protected and rows["rpcd"].protected
    assert rows["sysntpd"].protected is None and (rows["sysntpd"].enabled, rows["sysntpd"].running) == (
        True,
        True,
    )
    assert (rows["cron"].enabled, rows["cron"].running) == (True, False)
    assert rows["dwr921-internet-led"].running  # the bench's own service, from the image


async def test_time_zones_add_utc_first(ctx: AppContext) -> None:
    zones = await ctx.system.timezones("ap2")
    assert zones.zones[0] == "UTC" and "Asia/Jerusalem" in zones.zones and zones.note is None


async def test_reads_work_during_a_run(ctx_guard_live: AppContext) -> None:
    assert (await ctx_guard_live.system.overview("ap2")).hostname == "OpenWrt"
    assert await ctx_guard_live.system.logs("ap2", "system", 100)


async def test_read_endpoints(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap2/system"
    overview = await authed.get(base)
    assert overview.status_code == 200 and overview.json()["model"] == "D-Link DWR-921 C3 (U-Boot)"
    logs = await authed.get(f"{base}/logs", params={"kind": "kernel", "lines": 100})
    assert logs.status_code == 200 and logs.json()[0]["message"].startswith("Linux version")
    assert (await authed.get(f"{base}/logs", params={"kind": "system", "lines": 7})).status_code == 422
    processes = await authed.get(f"{base}/processes")
    assert processes.status_code == 200 and processes.json()["column"] == "RSS"
    services = await authed.get(f"{base}/services")
    assert services.status_code == 200 and any(r["name"] == "dropbear" for r in services.json())
    zones = await authed.get(f"{base}/timezones")
    assert zones.status_code == 200 and zones.json()["zones"][0] == "UTC"
    assert (await authed.get("/api/routers/nosuch/system")).status_code == 404
